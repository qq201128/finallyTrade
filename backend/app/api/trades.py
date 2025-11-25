"""
交易相关API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from pydantic import BaseModel
from datetime import datetime, timedelta
from app.core.database import get_db
from app.models.trade import Position, Order, PnLRecord, OrderStatus, OrderSide, OrderType
from app.models.strategy import UserStrategy
from app.models.user import User
from app.api.auth import get_current_user
from app.services.exchange_service import ExchangeService
from app.core.config import settings
import logging
import re
import asyncio
from threading import Lock
import time

logger = logging.getLogger(__name__)

# 价格缓存优化：{symbol: (price, timestamp, exchange)}
_price_cache: Dict[str, tuple] = {}
_cache_lock = Lock()
CACHE_TTL = 10  # 缓存10秒（提高TTL减少API调用）
MAX_CACHE_SIZE = 1000  # 最大缓存条目数，防止内存溢出

router = APIRouter(prefix="/api/trades", tags=["trades"])


def _parse_timeframe(timeframe: str) -> int:
    """解析时间周期字符串，返回秒数"""
    match = re.match(r'(\d+)([smhd])', timeframe.lower())
    if not match:
        return 3600  # 默认1小时
    
    value = int(match.group(1))
    unit = match.group(2)
    
    if unit == 's':
        return value
    elif unit == 'm':
        return value * 60
    elif unit == 'h':
        return value * 3600
    elif unit == 'd':
        return value * 86400
    else:
        return 3600


def _get_candle_start_timestamp(timestamp: datetime, timeframe: str) -> datetime:
    """获取K线周期的开始时间戳"""
    seconds = _parse_timeframe(timeframe)
    unix_timestamp = int(timestamp.timestamp())
    candle_start = unix_timestamp // seconds * seconds
    return datetime.fromtimestamp(candle_start)


def _calculate_margin_used(position: Position) -> Optional[float]:
    """计算持仓占用的保证金（名义价值 / 杠杆）"""
    entry_price = position.entry_price or 0
    size = abs(position.size or 0)
    leverage = position.leverage or 1
    if leverage <= 0:
        leverage = 1
    if entry_price <= 0 or size <= 0:
        return None
    # 保证金 = 名义价值 / 杠杆
    notional = entry_price * size
    margin = notional / leverage
    return margin


def _calculate_pnl_percentage(position: Position) -> Optional[float]:
    """计算未实现盈亏百分比（基于保证金）"""
    entry_price = position.entry_price or 0
    size = abs(position.size or 0)
    unrealized = position.unrealized_pnl
    leverage = position.leverage or 1
    if leverage <= 0:
        leverage = 1
    if entry_price <= 0 or size <= 0:
        return None
    # 计算保证金
    notional = entry_price * size
    margin_used = notional / leverage
    # 盈亏百分比 = (未实现盈亏 / 保证金) * 100
    if margin_used > 0 and unrealized is not None:
        return (unrealized / margin_used) * 100
    return None


class PositionResponse(BaseModel):
    id: int
    symbol: str
    side: str
    size: float
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    leverage: Optional[int] = 1  # 杠杆倍数
    margin_used: Optional[float] = None  # 占用保证金
    pnl_percentage: Optional[float] = None  # 盈亏百分比
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    is_open: bool

    class Config:
        from_attributes = True


class OrderResponse(BaseModel):
    id: int
    symbol: str
    side: str
    type: str
    amount: float
    price: Optional[float] = None  # 限价单有价格，市价单可能为None
    status: str
    filled: float
    cost: Optional[float] = None  # 未成交订单可能为None
    fee: Optional[float] = None  # 未成交订单可能为None
    realized_pnl: Optional[float] = None  # 已实现盈亏（仅平仓订单有）
    pnl_percentage: Optional[float] = None  # 盈亏百分比（仅平仓订单有）

    class Config:
        from_attributes = True


class PnLResponse(BaseModel):
    id: int
    symbol: str
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    size: Optional[float] = None
    realized_pnl: Optional[float] = None
    pnl_percentage: Optional[float] = None
    closed_at: Optional[str] = None

    class Config:
        from_attributes = True


def _get_cached_price(symbol: str) -> Optional[float]:
    """从缓存获取价格（优化：支持过期清理）"""
    current_time = time.time()
    with _cache_lock:
        if symbol in _price_cache:
            price, timestamp, _ = _price_cache[symbol]
            if current_time - timestamp < CACHE_TTL:
                return price
            else:
                # 过期，删除
                del _price_cache[symbol]
        return None


def _set_cached_price(symbol: str, price: float, exchange: str = ""):
    """设置价格缓存（优化：限制缓存大小，定期清理过期项）"""
    current_time = time.time()
    with _cache_lock:
        # 如果缓存过大，清理最旧的条目
        if len(_price_cache) >= MAX_CACHE_SIZE:
            # 清理过期项
            expired_keys = [
                key for key, (_, timestamp, _) in _price_cache.items()
                if current_time - timestamp >= CACHE_TTL
            ]
            for key in expired_keys:
                del _price_cache[key]
            
            # 如果清理后仍然过大，删除最旧的20%
            if len(_price_cache) >= MAX_CACHE_SIZE:
                sorted_items = sorted(
                    _price_cache.items(),
                    key=lambda x: x[1][1]  # 按timestamp排序
                )
                items_to_remove = len(sorted_items) // 5  # 删除20%
                for key, _ in sorted_items[:items_to_remove]:
                    del _price_cache[key]
        
        _price_cache[symbol] = (price, current_time, exchange)


async def _fetch_ticker_price(exchange_service: ExchangeService, symbol: str) -> Optional[float]:
    """异步获取交易对价格（在线程池中执行同步调用）"""
    try:
        # 先检查缓存
        cached_price = _get_cached_price(symbol)
        if cached_price is not None:
            return cached_price
        
        # 使用交易所服务的异步获取方法（内部封装线程池+局部缓存）
        current_price = await exchange_service.get_ticker_price_async(symbol)
        
        if current_price and current_price > 0:
            _set_cached_price(symbol, current_price, exchange_service.exchange.id if hasattr(exchange_service, 'exchange') else "")
            return current_price
        return None
    except Exception as e:
        logger.error(f"获取 {symbol} 当前价格失败: {e}")
        return None


@router.get("/positions", response_model=List[PositionResponse])
async def get_positions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    fast: bool = True  # 快速模式：先返回数据库数据，价格异步更新
):
    """获取用户持仓（快速模式：先返回数据库数据，价格通过WebSocket异步更新）"""
    positions = db.query(Position).filter(
        Position.user_id == current_user.id,
        Position.is_open == True
    ).all()
    
    if not positions:
        return []
    
    # 快速模式：直接使用数据库中的价格，不等待实时价格获取
    # 价格会通过WebSocket实时更新
    if fast:
        for position in positions:
            # 使用数据库中的当前价格（如果有）
            current_price = position.current_price or position.entry_price
            
            if current_price and current_price > 0 and position.entry_price:
                qty = abs(position.size or 0)
                if position.side == 'long':
                    position.unrealized_pnl = (current_price - position.entry_price) * qty
                else:
                    position.unrealized_pnl = (position.entry_price - current_price) * qty
            
            position.margin_used = _calculate_margin_used(position)
            position.pnl_percentage = _calculate_pnl_percentage(position)
        
        # 后台异步更新价格（不阻塞响应）
        asyncio.create_task(_update_prices_async(positions, db))
        
        return positions
    
    # 完整模式：等待所有价格获取完成（用于手动刷新）
    strategy_ids = {pos.user_strategy_id for pos in positions}
    strategies = db.query(UserStrategy).filter(
        UserStrategy.id.in_(strategy_ids)
    ).all()
    strategy_map = {s.id: s for s in strategies}
    exchange_cache: Dict[str, ExchangeService] = {}
    
    # 准备并发任务：按交易所分组，减少重复创建
    price_tasks = []
    position_info = []  # 保存持仓和对应的策略信息
    
    for position in positions:
        strategy = strategy_map.get(position.user_strategy_id)
        if not strategy:
            continue
        
        cache_key = f"{strategy.exchange}_{strategy.api_key}"
        if cache_key not in exchange_cache:
            exchange_cache[cache_key] = ExchangeService(
                exchange_name=strategy.exchange,
                api_key=strategy.api_key,
                api_secret=strategy.api_secret
            )
        exchange_service = exchange_cache[cache_key]
        
        # 创建异步任务
        task = _fetch_ticker_price(exchange_service, position.symbol)
        price_tasks.append(task)
        position_info.append((position, strategy))
    
    # 并发获取所有价格（带超时）
    if price_tasks:
        try:
            prices = await asyncio.wait_for(
                asyncio.gather(*price_tasks, return_exceptions=True),
                timeout=3.0  # 3秒超时
            )
        except asyncio.TimeoutError:
            logger.warning("价格获取超时，使用缓存价格")
            prices = [None] * len(price_tasks)
        except Exception as e:
            logger.error(f"并发获取价格失败: {e}")
            prices = [None] * len(price_tasks)
    else:
        prices = []
    
    # 更新持仓数据
    for (position, strategy), price_result in zip(position_info, prices):
        if isinstance(price_result, Exception):
            logger.error(f"获取 {position.symbol} 价格异常: {price_result}")
            current_price = position.current_price or position.entry_price
        elif price_result is not None:
            current_price = price_result
        else:
            # 如果获取失败，使用缓存或现有价格
            cached_price = _get_cached_price(position.symbol)
            current_price = cached_price if cached_price is not None else (position.current_price or position.entry_price)
        
        if current_price and current_price > 0 and position.entry_price:
            position.current_price = current_price
            qty = abs(position.size or 0)
            if position.side == 'long':
                position.unrealized_pnl = (current_price - position.entry_price) * qty
            else:
                position.unrealized_pnl = (position.entry_price - current_price) * qty
        
        position.margin_used = _calculate_margin_used(position)
        position.pnl_percentage = _calculate_pnl_percentage(position)
    
    return positions


async def _update_prices_async(positions: List[Position], db: Session):
    """后台异步更新价格（不阻塞主请求）"""
    # 创建新的数据库会话，因为原会话可能已关闭
    from app.core.database import SessionLocal
    new_db = SessionLocal()
    try:
        # 获取持仓ID列表
        position_ids = [pos.id for pos in positions]
        
        # 重新查询持仓（使用新的会话）
        positions_to_update = new_db.query(Position).filter(
            Position.id.in_(position_ids)
        ).all()
        
        if not positions_to_update:
            return
        
        strategy_ids = {pos.user_strategy_id for pos in positions_to_update}
        strategies = new_db.query(UserStrategy).filter(
            UserStrategy.id.in_(strategy_ids)
        ).all()
        strategy_map = {s.id: s for s in strategies}
        exchange_cache: Dict[str, ExchangeService] = {}
        
        price_tasks = []
        position_info = []
        
        for position in positions_to_update:
            strategy = strategy_map.get(position.user_strategy_id)
            if not strategy:
                continue
            
            cache_key = f"{strategy.exchange}_{strategy.api_key}"
            if cache_key not in exchange_cache:
                exchange_cache[cache_key] = ExchangeService(
                    exchange_name=strategy.exchange,
                    api_key=strategy.api_key,
                    api_secret=strategy.api_secret
                )
            exchange_service = exchange_cache[cache_key]
            
            task = _fetch_ticker_price(exchange_service, position.symbol)
            price_tasks.append(task)
            position_info.append((position, strategy))
        
        if price_tasks:
            prices = await asyncio.gather(*price_tasks, return_exceptions=True)
            
            # 更新数据库中的价格（用于下次快速加载）
            for (position, strategy), price_result in zip(position_info, prices):
                if isinstance(price_result, Exception):
                    continue
                elif price_result is not None and price_result > 0:
                    position.current_price = price_result
                    # 更新未实现盈亏
                    if position.entry_price:
                        qty = abs(position.size or 0)
                        if position.side == 'long':
                            position.unrealized_pnl = (price_result - position.entry_price) * qty
                        else:
                            position.unrealized_pnl = (position.entry_price - price_result) * qty
            
            new_db.commit()
    except Exception as e:
        logger.error(f"后台更新价格失败: {e}")
        new_db.rollback()
    finally:
        new_db.close()


@router.get("/reentry-blocks")
async def get_reentry_blocks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取当前用户所有策略的再入场限制"""
    blocks = []
    strategies = db.query(UserStrategy).filter(
        UserStrategy.user_id == current_user.id
    ).all()
    
    now = datetime.now()
    for strategy in strategies:
        config = strategy.config or {}
        last_close_times = config.get('last_close_candle_times', {})
        timeframe = strategy.timeframe or '1h'
        seconds = _parse_timeframe(timeframe)
        
        for key, timestamp_str in last_close_times.items():
            try:
                ts = datetime.fromisoformat(timestamp_str)
            except (ValueError, TypeError):
                continue
            
            blocked_until = ts + timedelta(seconds=seconds)
            if now >= blocked_until:
                # 自动过期，跳过（保留原数据以供引擎清理）
                continue
            
            if '_' in key:
                symbol, side = key.rsplit('_', 1)
            else:
                symbol = key
                side = 'long'
            
            blocks.append({
                "user_strategy_id": strategy.id,
                "symbol": symbol,
                "side": side,
                "blocked_until": blocked_until.isoformat(),
                "timeframe": timeframe
            })
    
    return blocks


class ReentryUnblockRequest(BaseModel):
    user_strategy_id: int
    symbol: str
    side: str


@router.post("/reentry-blocks/unblock")
async def unblock_reentry(
    req: ReentryUnblockRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手动清除指定策略与方向的再入场限制"""
    strategy = db.query(UserStrategy).filter(
        UserStrategy.id == req.user_strategy_id,
        UserStrategy.user_id == current_user.id
    ).first()
    
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    
    if not strategy.config:
        strategy.config = {}
    
    last_close_times = strategy.config.get('last_close_candle_times', {})
    key = f"{req.symbol}_{req.side}"
    
    if key in last_close_times:
        del last_close_times[key]
        strategy.config['last_close_candle_times'] = last_close_times
        db.commit()
        return {"message": "已解除限制"}
    
    return {"message": "当前未限制"}


class PositionHistoryResponse(BaseModel):
    """持仓历史记录响应"""
    id: int
    symbol: str
    side: str
    size: float
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    leverage: Optional[int] = 1
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: Optional[str] = None
    closed_at: Optional[str] = None
    realized_pnl: Optional[float] = None  # 从PnLRecord获取
    duration: Optional[str] = None  # 持仓持续时间

    class Config:
        from_attributes = True


@router.get("/positions/history", response_model=List[PositionHistoryResponse])
async def get_positions_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 100
):
    """获取用户持仓历史记录（已平仓的持仓，优化：批量查询PnL记录）"""
    from sqlalchemy import func
    from datetime import timedelta
    
    # 获取已平仓的持仓
    positions = db.query(Position).filter(
        Position.user_id == current_user.id,
        Position.is_open == False,
        Position.closed_at.isnot(None)
    ).order_by(Position.closed_at.desc()).limit(limit).all()
    
    # 批量获取所有持仓的PnL记录，避免N+1查询
    position_ids = [pos.id for pos in positions]
    pnl_records_map = {}
    if position_ids:
        pnl_records = db.query(PnLRecord).filter(
            PnLRecord.position_id.in_(position_ids)
        ).all()
        for pnl in pnl_records:
            # 每个持仓可能有多条PnL记录，取第一条（或可以聚合）
            if pnl.position_id not in pnl_records_map:
                pnl_records_map[pnl.position_id] = pnl
    
    result = []
    for position in positions:
        # 从映射中获取已实现盈亏
        pnl_record = pnl_records_map.get(position.id)
        realized_pnl = pnl_record.realized_pnl if pnl_record else None
        
        # 计算持仓持续时间
        duration = None
        if position.opened_at and position.closed_at:
            delta = position.closed_at - position.opened_at
            days = delta.days
            hours, remainder = divmod(delta.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            duration_parts = []
            if days > 0:
                duration_parts.append(f"{days}天")
            if hours > 0:
                duration_parts.append(f"{hours}小时")
            if minutes > 0:
                duration_parts.append(f"{minutes}分钟")
            
            duration = " ".join(duration_parts) if duration_parts else "小于1分钟"
        
        result.append({
            "id": position.id,
            "symbol": position.symbol,
            "side": position.side,
            "size": position.size,
            "entry_price": position.entry_price,
            "current_price": position.current_price,
            "leverage": position.leverage,
            "stop_loss": position.stop_loss,
            "take_profit": position.take_profit,
            "opened_at": position.opened_at.isoformat() if position.opened_at else None,
            "closed_at": position.closed_at.isoformat() if position.closed_at else None,
            "realized_pnl": realized_pnl,
            "duration": duration
        })
    
    return result


@router.get("/orders", response_model=List[OrderResponse])
async def get_orders(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str = None
):
    """获取用户订单（优化：使用joinedload避免N+1查询）"""
    from sqlalchemy.orm import joinedload
    
    query = db.query(Order).filter(Order.user_id == current_user.id)
    if status:
        query = query.filter(Order.status == status)
    # 使用joinedload预加载关联数据，避免N+1查询
    orders = query.options(
        joinedload(Order.position).joinedload(Position.user_strategy)
    ).order_by(Order.created_at.desc()).limit(100).all()
    
    # 批量获取所有需要的position_id和PnL记录
    position_ids = [order.position_id for order in orders if order.position_id]
    pnl_records_map = {}
    if position_ids:
        # 一次性查询所有相关的PnL记录
        pnl_records = db.query(PnLRecord).filter(
            PnLRecord.position_id.in_(position_ids)
        ).order_by(PnLRecord.closed_at.desc()).all()
        
        # 按position_id和size建立映射
        for pnl in pnl_records:
            key = (pnl.position_id, pnl.size)
            if key not in pnl_records_map:
                pnl_records_map[key] = pnl
    
    # 为每个订单添加盈亏信息（如果是平仓订单）
    result = []
    for order in orders:
        order_data = {
            "id": order.id,
            "symbol": order.symbol,
            "side": order.side.value if hasattr(order.side, 'value') else str(order.side),
            "type": order.type.value if hasattr(order.type, 'value') else str(order.type),
            "amount": order.amount,
            "price": order.price,
            "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
            "filled": order.filled,
            "cost": order.cost,
            "fee": order.fee,
            "realized_pnl": None,
            "pnl_percentage": None
        }
        
        # 如果是平仓订单（有position_id），查找对应的盈亏记录
        if order.position_id:
            # 先尝试精确匹配（position_id + filled）
            key = (order.position_id, order.filled)
            pnl_record = pnl_records_map.get(key)
            
            if not pnl_record:
                # 如果没有精确匹配，查找该持仓最新的盈亏记录
                for (pos_id, size), pnl in pnl_records_map.items():
                    if pos_id == order.position_id:
                        pnl_record = pnl
                        break
            
            if pnl_record:
                order_data["realized_pnl"] = pnl_record.realized_pnl
                order_data["pnl_percentage"] = pnl_record.pnl_percentage
        
        result.append(order_data)
    
    return result


@router.get("/pnl", response_model=List[PnLResponse])
async def get_pnl_records(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 100
):
    """获取用户盈亏记录"""
    records = db.query(PnLRecord).filter(
        PnLRecord.user_id == current_user.id
    ).order_by(PnLRecord.closed_at.desc()).limit(limit).all()
    
    # 转换为响应格式，确保 closed_at 是字符串
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "entry_price": r.entry_price,
            "exit_price": r.exit_price,
            "size": r.size,
            "realized_pnl": r.realized_pnl,
            "pnl_percentage": r.pnl_percentage,
            "closed_at": r.closed_at.isoformat() if r.closed_at else None
        }
        for r in records
    ]


@router.get("/pnl/total")
async def get_total_realized_pnl(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取用户所有已实现盈亏的总和"""
    from sqlalchemy import func
    
    total = db.query(func.sum(PnLRecord.realized_pnl)).filter(
        PnLRecord.user_id == current_user.id
    ).scalar() or 0.0
    
    return {"total_realized_pnl": float(total)}


@router.post("/positions/{position_id}/close")
async def close_position(
    position_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手动平仓"""
    # 获取持仓
    position = db.query(Position).filter(
        Position.id == position_id,
        Position.user_id == current_user.id,
        Position.is_open == True
    ).first()
    
    if not position:
        raise HTTPException(status_code=404, detail="持仓不存在或已平仓")
    
    # 获取用户策略配置
    user_strategy = db.query(UserStrategy).filter(
        UserStrategy.id == position.user_strategy_id
    ).first()
    
    if not user_strategy:
        raise HTTPException(status_code=404, detail="策略配置不存在")
    
    try:
        # 获取当前价格
        current_price = position.current_price
        if not current_price or current_price <= 0:
            # 如果当前价格不可用，尝试从交易所获取
            try:
                exchange_service = ExchangeService(
                    exchange_name=user_strategy.exchange,
                    api_key=user_strategy.api_key,
                    api_secret=user_strategy.api_secret
                )
                current_price = await exchange_service.get_ticker_price_async(
                    position.symbol,
                    use_cache=False,
                    cache_ttl=settings.CACHE_TICKER_TTL
                )
                if current_price > 0:
                    position.current_price = current_price
            except Exception as e:
                logger.error(f"获取当前价格失败: {e}")
                # 如果无法获取价格，使用开仓价（模拟平仓）
                current_price = position.entry_price
        
        # 如果是模拟模式，直接创建已成交订单并关闭持仓
        if user_strategy.is_simulated:
            # 保存原始持仓数量
            position_size = position.size
            entry_price = position.entry_price
            
            logger.info(f"[模拟模式] 手动平仓: {position.symbol}, 数量: {position_size}, 价格: {current_price}")
            
            # 创建模拟订单
            order = Order(
                user_id=position.user_id,
                position_id=position.id,
                exchange_order_id=f"SIM_{datetime.now().timestamp()}",
                symbol=position.symbol,
                side=OrderSide.SELL,
                type=OrderType.MARKET,
                amount=position_size,
                price=current_price,
                filled=position_size,
                cost=current_price * position_size,
                status=OrderStatus.FILLED,
                filled_at=datetime.now()
            )
            db.add(order)
            
            # 计算已实现盈亏
            realized_pnl = (current_price - entry_price) * position_size
            
            # 关闭持仓
            position.is_open = False
            position.size = 0
            position.closed_at = datetime.now()
            
            # 记录平仓时的K线周期时间戳，用于防止同一周期内立即开仓
            timeframe = user_strategy.timeframe if user_strategy.timeframe else '1h'
            close_candle_timestamp = _get_candle_start_timestamp(datetime.now(), timeframe)
            
            # 保存到用户策略配置中
            if not user_strategy.config:
                user_strategy.config = {}
            if 'last_close_candle_times' not in user_strategy.config:
                user_strategy.config['last_close_candle_times'] = {}
            user_strategy.config['last_close_candle_times'][position.symbol] = close_candle_timestamp.isoformat()
            
            # 创建盈亏记录
            effective_leverage = position.leverage or 1
            if effective_leverage <= 0:
                effective_leverage = 1
            
            pnl_record = PnLRecord(
                user_id=position.user_id,
                user_strategy_id=position.user_strategy_id,
                position_id=position.id,
                symbol=position.symbol,
                entry_price=entry_price,
                exit_price=current_price,
                size=position_size,
                realized_pnl=realized_pnl,
                pnl_percentage=(
                    (realized_pnl / (entry_price * position_size)) * effective_leverage * 100
                    if entry_price > 0 and position_size > 0 else 0
                )
            )
            db.add(pnl_record)
            db.commit()
            
            # 推送 WebSocket 更新：通知前端持仓已关闭
            try:
                from app.api.websocket import manager
                # 发送已关闭的持仓信息（is_open=False）
                position_data = {
                    "id": position.id,
                    "symbol": position.symbol,
                    "side": position.side,
                    "size": 0,
                    "entry_price": position.entry_price,
                    "current_price": current_price,
                    "unrealized_pnl": 0,
                    "leverage": position.leverage or 1,
                    "margin_used": 0,
                    "pnl_percentage": 0,
                    "is_open": False
                }
                message = {
                    "type": "positions",
                    "data": [position_data]
                }
                # 发送给该用户的所有连接
                for connection in manager.active_connections:
                    connection_user_id = manager.connection_users.get(connection)
                    if connection_user_id == position.user_id:
                        try:
                            await manager.send_personal_message(message, connection)
                        except Exception as e:
                            logger.debug(f"推送平仓更新失败: {e}")
            except Exception as e:
                logger.warning(f"推送 WebSocket 更新失败: {e}")
            
            logger.info(f"[模拟模式] 平仓完成: 持仓 {position.id}, 盈亏: {realized_pnl}, 记录K线周期: {close_candle_timestamp}")
            return {"message": "平仓成功", "order_id": order.id, "realized_pnl": realized_pnl}
        
        # 实际模式：创建市价平仓订单
        exchange_service = ExchangeService(
            exchange_name=user_strategy.exchange,
            api_key=user_strategy.api_key,
            api_secret=user_strategy.api_secret
        )
        
        # 创建市价卖出订单
        exchange_order = exchange_service.create_order(
            symbol=position.symbol,
            side='sell',
            order_type='market',
            amount=position.size
        )
        
        # 创建订单记录
        order = Order(
            user_id=position.user_id,
            position_id=position.id,
            exchange_order_id=exchange_order.get('id'),
            symbol=position.symbol,
            side=OrderSide.SELL,
            type=OrderType.MARKET,
            amount=position.size,
            status=OrderStatus.PENDING
        )
        db.add(order)
        db.commit()
        
        logger.info(f"创建平仓订单: {order.id}, 交易所订单ID: {exchange_order.get('id')}")
        return {"message": "平仓订单已创建", "order_id": order.id}
        
    except Exception as e:
        db.rollback()
        logger.error(f"平仓失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"平仓失败: {str(e)}")

