"""
WebSocket API - 实时数据推送
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import json
import logging
import asyncio
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.trade import Position, Order
from app.models.user import User
from app.api.auth import get_current_user

logger = logging.getLogger(__name__)


def _calculate_unrealized_pnl(position: Position, current_price: float) -> float:
    """
    统一的未实现盈亏计算（根据方向及绝对仓位）
    """
    if not current_price or not position.entry_price:
        return 0.0
    
    qty = abs(position.size or 0)
    if qty == 0:
        return 0.0
    
    if position.side == 'short':
        return (position.entry_price - current_price) * qty
    return (current_price - position.entry_price) * qty


def _calculate_margin_used(position: Position) -> Optional[float]:
    """计算持仓保证金（名义价值 / 杠杆）"""
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
    """计算盈亏百分比（基于保证金）"""
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

router = APIRouter(prefix="/api/ws", tags=["websocket"])


class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        # 连接和用户ID的映射 {websocket: user_id}
        self.connection_users: Dict[WebSocket, int] = {}
        # 全局的价格订阅任务管理 {symbol: asyncio.Task}
        self.global_ticker_tasks: Dict[str, asyncio.Task] = {}
        # 价格缓存 {symbol: latest_price_info}
        self.global_price_cache: Dict[str, dict] = {}
        # 订阅计数器 {symbol: count} - 记录有多少个连接在使用这个订阅
        self.subscription_refs: Dict[str, int] = {}
        # ExchangeService 实例缓存 {cache_key: ExchangeService}
        self.global_exchange_services: Dict[str, Any] = {}
    
    async def connect(self, websocket: WebSocket, user_id: int = None):
        """接受WebSocket连接"""
        await websocket.accept()
        self.active_connections.append(websocket)
        if user_id:
            self.connection_users[websocket] = user_id
        logger.info(f"WebSocket连接已建立，当前连接数: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """断开WebSocket连接"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.connection_users:
            user_id = self.connection_users.pop(websocket)
            logger.info(f"WebSocket连接已断开: 用户 {user_id}，当前连接数: {len(self.active_connections)}")
        else:
            logger.info(f"WebSocket连接已断开，当前连接数: {len(self.active_connections)}")
    
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """发送个人消息"""
        await websocket.send_json(message)
    
    async def broadcast(self, message: dict):
        """广播消息给所有连接"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"广播消息失败: {e}")
    
    def get_or_create_ticker_subscription(self, symbol: str, exchange_service: Any, strategy_info: Dict[str, Any], db: Session):
        """获取或创建价格订阅（全局共享）"""
        if symbol in self.global_ticker_tasks:
            # 检查任务是否还在运行
            task = self.global_ticker_tasks[symbol]
            if not task.done():
                # 订阅已存在且运行中，增加引用计数
                self.subscription_refs[symbol] = self.subscription_refs.get(symbol, 0) + 1
                logger.debug(f"复用现有的 {symbol} 价格订阅（引用计数: {self.subscription_refs[symbol]}）")
                return True
        
        # 创建新的订阅
        import asyncio
        task = asyncio.create_task(
            self._watch_price_global(symbol, exchange_service, strategy_info, db)
        )
        self.global_ticker_tasks[symbol] = task
        self.subscription_refs[symbol] = 1
        logger.info(f"创建新的 {symbol} 价格订阅（引用计数: 1）")
        return True
    
    def release_ticker_subscription(self, symbol: str):
        """释放价格订阅引用"""
        if symbol in self.subscription_refs:
            self.subscription_refs[symbol] = max(0, self.subscription_refs[symbol] - 1)
            count = self.subscription_refs[symbol]
            logger.debug(f"释放 {symbol} 价格订阅引用（剩余引用: {count}）")
            
            # 如果没有引用了，取消订阅任务
            if count == 0:
                if symbol in self.global_ticker_tasks:
                    task = self.global_ticker_tasks[symbol]
                    if not task.done():
                        task.cancel()
                        logger.info(f"取消 {symbol} 的价格订阅（无引用）")
                    del self.global_ticker_tasks[symbol]
                if symbol in self.global_price_cache:
                    del self.global_price_cache[symbol]
                if symbol in self.subscription_refs:
                    del self.subscription_refs[symbol]
    
    async def _watch_price_global(self, symbol: str, exchange_service: Any, strategy_info: Dict[str, Any], db: Session):
        """全局价格订阅任务（所有连接共享）"""
        use_polling = False
        
        # 先尝试使用 WebSocket（如果启用）
        if settings.WS_ENABLED:
            try:
                logger.debug(f"尝试使用 WebSocket 订阅 {symbol} 实时价格")
                # 尝试使用 WebSocket 订阅
                async for ticker in exchange_service.watch_ticker(symbol):
                    if ticker:
                        current_price = ticker.get('last', 0)
                        bid_price = ticker.get('bid', 0)
                        ask_price = ticker.get('ask', 0)
                        
                        # 更新全局价格缓存
                        self.global_price_cache[symbol] = {
                            'last': current_price,
                            'bid': bid_price,
                            'ask': ask_price,
                            'high': ticker.get('high', 0),
                            'low': ticker.get('low', 0),
                            'open': ticker.get('open', 0),
                            'volume': ticker.get('quoteVolume', 0),
                            'timestamp': ticker.get('timestamp', 0)
                        }
                        
                        # 广播给所有连接的客户端
                        await self._broadcast_price_update(symbol, current_price, db)
            except asyncio.CancelledError:
                logger.info(f"{symbol} 价格订阅任务被取消")
                raise
            except Exception as e:
                logger.warning(f"WebSocket订阅 {symbol} 实时价格失败: {e}，切换到轮询模式")
                use_polling = True
        else:
            logger.info(f"WebSocket未启用，直接使用轮询模式获取 {symbol} 价格")
            use_polling = True
        
        # 使用轮询模式（WebSocket 失败或未启用时）
        if use_polling:
            logger.info(f"使用轮询模式获取 {symbol} 价格（每2秒）")
            while symbol in self.subscription_refs and self.subscription_refs[symbol] > 0:
                try:
                    ticker = exchange_service.exchange.fetch_ticker(symbol)
                    current_price = ticker.get('last', 0)
                    
                    if current_price > 0:
                        logger.debug(
                            f"[轮询价格] 交易对: {symbol} | 最新价(last): {current_price} | 交易所: {strategy_info.get('exchange')}"
                        )
                        
                        # 更新全局价格缓存
                        self.global_price_cache[symbol] = {
                            'last': current_price,
                            'bid': ticker.get('bid', 0),
                            'ask': ticker.get('ask', 0),
                            'high': ticker.get('high', 0),
                            'low': ticker.get('low', 0),
                            'open': ticker.get('open', 0),
                            'volume': ticker.get('quoteVolume', 0),
                            'timestamp': ticker.get('timestamp', 0)
                        }
                        
                        await self._broadcast_price_update(symbol, current_price, db)
                    
                    await asyncio.sleep(2)  # 每2秒轮询一次
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"轮询 {symbol} 价格失败: {e}")
                    await asyncio.sleep(5)  # 出错时等待更长时间
    
    async def _broadcast_price_update(self, symbol: str, current_price: float, db: Session):
        """广播价格更新给所有连接的客户端"""
        if current_price <= 0:
            return
        
        # 为所有有该交易对持仓的用户更新并推送
        from app.models.trade import Position
        from app.models.strategy import UserStrategy
        
        # 获取所有有该交易对持仓的用户
        positions = db.query(Position).filter(
            Position.symbol == symbol,
            Position.is_open == True
        ).all()
        
        if not positions:
            return
        
        # 按用户分组
        user_positions = {}
        for position in positions:
            if position.user_id not in user_positions:
                user_positions[position.user_id] = []
            user_positions[position.user_id].append(position)
        
        # 为每个用户更新并推送
        for user_id, user_pos_list in user_positions.items():
            position_data = []
            for position in user_pos_list:
                old_price = position.current_price
                position.current_price = current_price
                if position.entry_price:
                    position.unrealized_pnl = _calculate_unrealized_pnl(position, current_price)
                
                margin_used = _calculate_margin_used(position)
                pnl_percentage = _calculate_pnl_percentage(position)
                
                position_data.append({
                    "id": position.id,
                    "symbol": position.symbol,
                    "side": position.side,
                    "size": position.size,
                    "entry_price": position.entry_price,
                    "current_price": current_price,
                    "unrealized_pnl": position.unrealized_pnl,
                    "leverage": position.leverage or 1,
                    "margin_used": margin_used,
                    "pnl_percentage": pnl_percentage
                })
            
            # 提交数据库更改
            db.commit()
            
            # 发送给所有该用户的连接
            message = {
                "type": "positions",
                "data": position_data
            }
            
            # 只发送给该用户的连接
            for connection in self.active_connections:
                try:
                    # 检查连接对应的用户ID是否匹配
                    connection_user_id = self.connection_users.get(connection)
                    if connection_user_id == user_id:
                        await connection.send_json(message)
                except Exception as e:
                    logger.debug(f"发送价格更新失败: {e}")


manager = ConnectionManager()


@router.websocket("/positions/{user_id}")
async def websocket_positions(websocket: WebSocket, user_id: int):
    """推送持仓实时更新（使用WebSocket实时价格推送）"""
    await manager.connect(websocket, user_id)
    db = SessionLocal()
    
    try:
        from app.models.strategy import UserStrategy
        from app.services.exchange_service import ExchangeService
        import asyncio
        
        # 记录这个连接订阅了哪些交易对（用于断开时清理）
        subscribed_symbols = set()
        
        # 初始化：获取所有持仓并启动订阅
        positions = db.query(Position).filter(
            Position.user_id == user_id,
            Position.is_open == True
        ).all()
        
        user_strategies = db.query(UserStrategy).filter(
            UserStrategy.user_id == user_id,
            UserStrategy.is_enabled == True
        ).all()
        
        # 为每个持仓启动或复用全局价格订阅
        for position in positions:
            user_strategy = next((us for us in user_strategies if us.id == position.user_strategy_id), None)
            if not user_strategy:
                continue
            
            # 创建或获取 ExchangeService 实例（全局缓存）
            strategy_info = {
                'exchange': user_strategy.exchange,
                'api_key': user_strategy.api_key,
                'api_secret': user_strategy.api_secret
            }
            cache_key = f"{user_strategy.exchange}_{user_strategy.api_key}"
            if cache_key not in manager.global_exchange_services:
                manager.global_exchange_services[cache_key] = ExchangeService(
                    exchange_name=user_strategy.exchange,
                    api_key=user_strategy.api_key,
                    api_secret=user_strategy.api_secret
                )
            
            exchange_service = manager.global_exchange_services[cache_key]
            
            # 获取或创建全局价格订阅（如果已存在则复用）
            if manager.get_or_create_ticker_subscription(position.symbol, exchange_service, strategy_info, db):
                subscribed_symbols.add(position.symbol)
        
        # 发送初始持仓数据（使用数据库中的价格或全局缓存）
        initial_position_data = []
        for position in positions:
            # 优先使用全局价格缓存
            current_price = position.current_price or 0
            if position.symbol in manager.global_price_cache:
                cached_price = manager.global_price_cache[position.symbol].get('last', 0)
                if cached_price > 0:
                    current_price = cached_price
            
            if position.entry_price and current_price:
                position.unrealized_pnl = _calculate_unrealized_pnl(position, current_price)
            
            margin_used = _calculate_margin_used(position)
            pnl_percentage = _calculate_pnl_percentage(position)
            
            initial_position_data.append({
                "id": position.id,
                "symbol": position.symbol,
                "side": position.side,
                "size": position.size,
                "entry_price": position.entry_price,
                "current_price": current_price,
                "unrealized_pnl": position.unrealized_pnl,
                "leverage": position.leverage or 1,
                "margin_used": margin_used,
                "pnl_percentage": pnl_percentage
            })
        
        await manager.send_personal_message({
            "type": "positions",
            "data": initial_position_data
        }, websocket)
        
        # 监听价格更新并推送给当前连接
        # 价格更新由全局订阅任务处理，这里只需要接收并过滤
        while True:
            # 定期检查价格缓存并推送更新（只推送该用户的持仓）
            for symbol in subscribed_symbols:
                if symbol in manager.global_price_cache:
                    price_info = manager.global_price_cache[symbol]
                    current_price = price_info.get('last', 0)
                    
                    if current_price > 0:
                        # 查找该用户该交易对的持仓
                        user_positions = [p for p in positions if p.symbol == symbol]
                        if user_positions:
                            position_data = []
                            for position in user_positions:
                                # 使用最新价格重新计算未实现盈亏，保持与后端一致
                                if position.entry_price and current_price:
                                    position.unrealized_pnl = _calculate_unrealized_pnl(position, current_price)
                                
                                margin_used = _calculate_margin_used(position)
                                pnl_percentage = _calculate_pnl_percentage(position)
                                
                                position_data.append({
                                    "id": position.id,
                                    "symbol": position.symbol,
                                    "side": position.side,
                                    "size": position.size,
                                    "entry_price": position.entry_price,
                                    "current_price": current_price,
                                    "unrealized_pnl": position.unrealized_pnl,
                                    "leverage": position.leverage or 1,
                                    "margin_used": margin_used,
                                    "pnl_percentage": pnl_percentage
                                })
                            
                            await manager.send_personal_message({
                                "type": "positions",
                                "data": position_data
                            }, websocket)
            
            await asyncio.sleep(0.5)  # 每0.5秒检查一次价格更新
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket连接断开: 用户 {user_id}")
    except Exception as e:
        logger.error(f"WebSocket错误: {e}", exc_info=True)
    finally:
        # 释放所有订阅引用
        for symbol in subscribed_symbols:
            manager.release_ticker_subscription(symbol)
        
        manager.disconnect(websocket)
        db.close()
        logger.info(f"WebSocket连接清理完成: 用户 {user_id}，已释放 {len(subscribed_symbols)} 个订阅")


@router.websocket("/orders/{user_id}")
async def websocket_orders(websocket: WebSocket, user_id: int):
    """推送订单实时更新"""
    await manager.connect(websocket)
    db = SessionLocal()
    
    try:
        while True:
            # 获取最新订单数据
            orders = db.query(Order).filter(
                Order.user_id == user_id
            ).order_by(Order.created_at.desc()).limit(50).all()
            
            # 发送订单数据
            await manager.send_personal_message({
                "type": "orders",
                "data": [
                    {
                        "id": o.id,
                        "symbol": o.symbol,
                        "side": o.side.value,
                        "type": o.type.value,
                        "amount": o.amount,
                        "price": o.price,
                        "status": o.status.value,
                        "filled": o.filled
                    }
                    for o in orders
                ]
            }, websocket)
            
            import asyncio
            await asyncio.sleep(3)  # 每3秒推送一次
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        manager.disconnect(websocket)
    finally:
        db.close()

