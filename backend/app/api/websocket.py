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
from app.services.monitoring import monitoring

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
        # 批量更新队列：{symbol: (current_price, timestamp)} - 用于批量更新数据库
        self._price_update_queue: Dict[str, tuple] = {}
        # 批量更新任务
        self._batch_update_task: Optional[asyncio.Task] = None
        # 持仓缓存：{symbol: [position_info]} - 缓存持仓信息，减少数据库查询
        self._positions_cache: Dict[str, List[Dict]] = {}
        # 持仓缓存更新时间戳
        self._positions_cache_timestamp: float = 0
        # 持仓缓存有效期（秒）
        self._positions_cache_ttl: float = 10.0
        # 批量更新任务将在有事件循环时启动（延迟初始化）
    
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
    
    def get_or_create_ticker_subscription(self, symbol: str, exchange_service: Any, strategy_info: Dict[str, Any], db: Session = None):
        """获取或创建价格订阅（全局共享，不依赖传入的db Session）"""
        if symbol in self.global_ticker_tasks:
            # 检查任务是否还在运行
            task = self.global_ticker_tasks[symbol]
            if not task.done():
                # 订阅已存在且运行中，增加引用计数
                self.subscription_refs[symbol] = self.subscription_refs.get(symbol, 0) + 1
                logger.debug(f"复用现有的 {symbol} 价格订阅（引用计数: {self.subscription_refs[symbol]}）")
                return True
        
        # 创建新的订阅（不传入db，让内部方法自己管理Session）
        import asyncio
        task = asyncio.create_task(
            self._watch_price_global(symbol, exchange_service, strategy_info)
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
    
    async def _watch_price_global(self, symbol: str, exchange_service: Any, strategy_info: Dict[str, Any]):
        """全局价格订阅任务（所有连接共享，内部管理数据库会话）"""
        use_polling = settings.FAILSAFE_POLLING_MODE
        
        # 先尝试使用 WebSocket（如果启用）
        if settings.WS_ENABLED and not use_polling:
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
                        
                        monitoring.record_event("price.update", tags={"symbol": symbol, "source": "ws"})
                        # 广播给所有连接的客户端（不传入db，让方法自己管理）
                        await self._broadcast_price_update(symbol, current_price)
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
            interval = settings.WS_POLLING_INTERVAL or 2.0
            logger.info(f"使用轮询模式获取 {symbol} 价格（每{interval}秒）")
            while symbol in self.subscription_refs and self.subscription_refs[symbol] > 0:
                try:
                    ticker = await exchange_service.fetch_ticker_async(symbol, use_cache=False)
                    if not ticker:
                        await asyncio.sleep(interval)
                        continue
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
                        
                        monitoring.record_event("price.update", tags={"symbol": symbol, "source": "poll"})
                        await self._broadcast_price_update(symbol, current_price)
                    
                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"轮询 {symbol} 价格失败: {e}", exc_info=True)
                    await asyncio.sleep(5)  # 出错时等待更长时间
    
    def _ensure_batch_update_task(self):
        """确保批量更新任务已启动（延迟初始化）"""
        import asyncio
        if self._batch_update_task is None or self._batch_update_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._batch_update_task = loop.create_task(self._batch_update_worker())
                logger.debug("批量更新任务已启动")
            except RuntimeError:
                # 如果没有运行的事件循环，将在下次有事件循环时启动
                logger.debug("当前无事件循环，批量更新任务将在下次启动")
    
    async def _broadcast_price_update(self, symbol: str, current_price: float, db: Session = None):
        """广播价格更新给所有连接的客户端（优化：实时推送，批量更新数据库）"""
        if current_price <= 0:
            return
        
        import time
        # 确保批量更新任务已启动
        self._ensure_batch_update_task()
        
        # 将价格更新加入批量更新队列（用于数据库更新）
        self._price_update_queue[symbol] = (current_price, time.time())
        
        # 实时推送价格更新给客户端（不等待数据库更新）
        await self._push_price_to_clients(symbol, current_price)
    
    async def _get_positions_for_symbol(self, symbol: str):
        """获取交易对的持仓信息（使用缓存，减少数据库查询）"""
        import time
        from app.models.trade import Position
        from app.core.database import get_db_context
        
        current_time = time.time()
        
        # 检查缓存是否有效
        if (symbol in self._positions_cache and 
            current_time - self._positions_cache_timestamp < self._positions_cache_ttl):
            return self._positions_cache[symbol]
        
        # 缓存失效，重新查询（使用单个Session批量查询所有持仓）
        try:
            with get_db_context() as read_db:
                positions = read_db.query(Position).filter(
                    Position.symbol == symbol,
                    Position.is_open == True
                ).all()
                
                # 转换为字典格式并缓存
                position_list = []
                for pos in positions:
                    position_list.append({
                        'id': pos.id,
                        'user_id': pos.user_id,
                        'symbol': pos.symbol,
                        'side': pos.side,
                        'size': pos.size,
                        'entry_price': pos.entry_price,
                        'leverage': pos.leverage or 1
                    })
                
                # 更新缓存
                self._positions_cache[symbol] = position_list
                self._positions_cache_timestamp = current_time
                
                return position_list
        except Exception as e:
            logger.error(f"查询持仓失败 {symbol}: {e}")
            return []
    
    async def _push_price_to_clients(self, symbol: str, current_price: float):
        """推送价格更新给客户端（使用缓存，不涉及数据库操作）"""
        try:
            # 从缓存获取持仓信息（避免频繁查询数据库）
            positions = await self._get_positions_for_symbol(symbol)
            
            if not positions:
                return
            
            # 按用户分组
            user_positions = {}
            for pos_info in positions:
                user_id = pos_info['user_id']
                if user_id not in user_positions:
                    user_positions[user_id] = []
                user_positions[user_id].append(pos_info)
            
            # 为每个用户推送更新（使用最新价格计算，但不更新数据库）
            for user_id, user_pos_list in user_positions.items():
                position_data = []
                for pos_info in user_pos_list:
                    try:
                        # 创建临时Position对象用于计算
                        class TempPosition:
                            def __init__(self, info):
                                self.entry_price = info['entry_price']
                                self.size = info['size']
                                self.leverage = info['leverage']
                                self.side = info['side']
                        
                        temp_pos = TempPosition(pos_info)
                        
                        # 使用最新价格计算盈亏
                        calculated_pnl = _calculate_unrealized_pnl(temp_pos, current_price)
                        temp_pos.unrealized_pnl = calculated_pnl
                        
                        margin_used = _calculate_margin_used(temp_pos)
                        pnl_percentage = _calculate_pnl_percentage(temp_pos)
                        
                        position_data.append({
                            "id": pos_info['id'],
                            "symbol": pos_info['symbol'],
                            "side": pos_info['side'],
                            "size": pos_info['size'],
                            "entry_price": pos_info['entry_price'],
                            "current_price": current_price,
                            "unrealized_pnl": calculated_pnl,
                            "leverage": pos_info['leverage'],
                            "margin_used": margin_used,
                            "pnl_percentage": pnl_percentage
                        })
                    except Exception as e:
                        logger.error(f"计算持仓 {pos_info['id']} 盈亏失败: {e}")
                        continue
                
                # 发送给所有该用户的连接
                message = {
                    "type": "positions",
                    "data": position_data
                }
                
                # 只发送给该用户的连接
                for connection in self.active_connections:
                    try:
                        connection_user_id = self.connection_users.get(connection)
                        if connection_user_id == user_id:
                            await connection.send_json(message)
                    except Exception as e:
                        logger.debug(f"发送价格更新失败: {e}")
        except Exception as e:
            logger.error(f"推送价格更新失败 {symbol}: {e}", exc_info=True)
    
    async def _batch_update_worker(self):
        """批量更新数据库的工作线程（降低数据库更新频率，避免连接池溢出）"""
        import asyncio
        from app.models.trade import Position
        from app.core.database import get_db_context
        
        # 每5秒批量更新一次数据库（而不是每次价格变化都更新）
        BATCH_UPDATE_INTERVAL = 5.0  # 5秒
        MAX_BATCH_SIZE = 50  # 每次最多更新50个持仓
        
        while True:
            try:
                await asyncio.sleep(BATCH_UPDATE_INTERVAL)
                
                # 获取待更新的价格
                if not self._price_update_queue:
                    continue
                
                # 复制队列并清空（避免并发修改）
                updates_to_process = dict(self._price_update_queue)
                self._price_update_queue.clear()
                
                if not updates_to_process:
                    continue
                
                # 批量更新数据库（使用单个Session）
                try:
                    with get_db_context() as update_db:
                        # 获取所有需要更新的持仓
                        symbols = list(updates_to_process.keys())
                        positions = update_db.query(Position).filter(
                            Position.symbol.in_(symbols),
                            Position.is_open == True
                        ).limit(MAX_BATCH_SIZE).all()
                        
                        if not positions:
                            continue
                        
                        # 批量更新
                        updated_count = 0
                        for position in positions:
                            if position.symbol in updates_to_process:
                                current_price, _ = updates_to_process[position.symbol]
                                try:
                                    position.current_price = current_price
                                    if position.entry_price:
                                        position.unrealized_pnl = _calculate_unrealized_pnl(position, current_price)
                                    updated_count += 1
                                except Exception as e:
                                    logger.error(f"批量更新持仓 {position.id} 失败: {e}")
                        
                        if updated_count > 0:
                            # 一次性提交所有更新
                            update_db.commit()
                            logger.debug(f"批量更新了 {updated_count} 个持仓的价格")
                            
                            # 清除相关缓存，强制下次重新查询
                            for symbol in updates_to_process.keys():
                                if symbol in self._positions_cache:
                                    del self._positions_cache[symbol]
                except Exception as e:
                    logger.error(f"批量更新数据库失败: {e}", exc_info=True)
                    
            except asyncio.CancelledError:
                logger.info("批量更新任务被取消")
                break
            except Exception as e:
                logger.error(f"批量更新工作线程错误: {e}", exc_info=True)
                await asyncio.sleep(5)  # 出错时等待更长时间


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
            
            # 获取或创建全局价格订阅（如果已存在则复用，不传入db）
            if manager.get_or_create_ticker_subscription(position.symbol, exchange_service, strategy_info):
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

