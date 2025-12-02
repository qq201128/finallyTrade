"""
WebSocket 推送工具模块
"""
import asyncio
import logging
from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.trade import Position

logger = logging.getLogger(__name__)


async def _push_message_async(message: Dict[str, Any], user_id: int):
    """
    异步推送消息到 WebSocket

    Args:
        message: 要推送的消息
        user_id: 用户ID
    """
    try:
        from app.api.websocket import manager
        # 发送给该用户的所有连接
        for connection in manager.active_connections:
            connection_user_id = manager.connection_users.get(connection)
            if connection_user_id == user_id:
                try:
                    await manager.send_personal_message(message, connection)
                except Exception as e:
                    logger.debug(f"推送更新失败: {e}")
    except Exception as e:
        logger.warning(f"推送 WebSocket 更新失败: {e}")


async def push_position_update_async(message: Dict[str, Any], user_id: int):
    """异步推送持仓更新到 WebSocket（兼容旧接口）"""
    await _push_message_async(message, user_id)


def push_position_update_sync(
    position: "Position",
    current_price: float,
    is_closed: bool = False
):
    """
    同步推送持仓更新到 WebSocket（在非异步上下文中使用）

    Args:
        position: 持仓对象
        current_price: 当前价格
        is_closed: 是否已平仓
    """
    try:
        # 构建消息
        message = build_position_message(
            position_id=position.id,
            symbol=position.symbol,
            side=position.side,
            size=0 if is_closed else position.size,
            entry_price=position.entry_price,
            current_price=current_price,
            unrealized_pnl=0 if is_closed else (position.unrealized_pnl or 0),
            leverage=position.leverage or 1,
            margin_used=0 if is_closed else None,
            pnl_percentage=0 if is_closed else None,
            is_open=not is_closed
        )

        user_id = position.user_id

        # 尝试获取当前事件循环
        try:
            loop = asyncio.get_running_loop()
            # 如果有运行中的事件循环，使用 create_task
            asyncio.create_task(_push_message_async(message, user_id))
        except RuntimeError:
            # 没有运行中的事件循环，使用 asyncio.run
            asyncio.run(_push_message_async(message, user_id))
    except Exception as e:
        logger.warning(f"推送 WebSocket 更新失败: {e}")


def build_position_message(
    position_id: int,
    symbol: str,
    side: str,
    size: float,
    entry_price: float,
    current_price: float,
    unrealized_pnl: float,
    leverage: int,
    margin_used: float,
    pnl_percentage: float,
    is_open: bool
) -> Dict[str, Any]:
    """
    构建持仓更新消息

    Args:
        position_id: 持仓ID
        symbol: 交易对
        side: 方向
        size: 数量
        entry_price: 开仓价格
        current_price: 当前价格
        unrealized_pnl: 未实现盈亏
        leverage: 杠杆
        margin_used: 占用保证金
        pnl_percentage: 盈亏百分比
        is_open: 是否开放

    Returns:
        消息字典
    """
    position_data = {
        "id": position_id,
        "symbol": symbol,
        "side": side,
        "size": size,
        "entry_price": entry_price,
        "current_price": current_price,
        "unrealized_pnl": unrealized_pnl,
        "leverage": leverage,
        "margin_used": margin_used,
        "pnl_percentage": pnl_percentage,
        "is_open": is_open
    }
    return {
        "type": "positions",
        "data": [position_data]
    }
