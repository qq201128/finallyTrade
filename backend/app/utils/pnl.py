"""
盈亏计算工具模块
"""
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.trade import Position


def calculate_unrealized_pnl(
    entry_price: float,
    current_price: float,
    size: float,
    side: str = 'long'
) -> float:
    """
    计算未实现盈亏（根据持仓方向）

    Args:
        entry_price: 开仓价格
        current_price: 当前价格
        size: 持仓数量（绝对值）
        side: 持仓方向 'long' 或 'short'

    Returns:
        未实现盈亏（正数表示盈利，负数表示亏损）
    """
    position_size = abs(size)
    if side == 'long':
        return (current_price - entry_price) * position_size
    else:
        return (entry_price - current_price) * position_size


def calculate_margin_used(
    entry_price: float,
    size: float,
    leverage: int = 1
) -> Optional[float]:
    """
    计算持仓占用的保证金（名义价值 / 杠杆）

    Args:
        entry_price: 开仓价格
        size: 持仓数量
        leverage: 杠杆倍数

    Returns:
        占用保证金，如果参数无效则返回 None
    """
    entry_price = entry_price or 0
    size = abs(size or 0)
    leverage = leverage or 1
    if leverage <= 0:
        leverage = 1
    if entry_price <= 0 or size <= 0:
        return None
    # 保证金 = 名义价值 / 杠杆
    notional = entry_price * size
    margin = notional / leverage
    return margin


def calculate_pnl_percentage(
    entry_price: float,
    size: float,
    unrealized_pnl: Optional[float],
    leverage: int = 1
) -> Optional[float]:
    """
    计算未实现盈亏百分比（基于保证金）

    Args:
        entry_price: 开仓价格
        size: 持仓数量
        unrealized_pnl: 未实现盈亏
        leverage: 杠杆倍数

    Returns:
        盈亏百分比，如果参数无效则返回 None
    """
    entry_price = entry_price or 0
    size = abs(size or 0)
    leverage = leverage or 1
    if leverage <= 0:
        leverage = 1
    if entry_price <= 0 or size <= 0:
        return None
    # 计算保证金
    notional = entry_price * size
    margin_used = notional / leverage
    # 盈亏百分比 = (未实现盈亏 / 保证金) * 100
    if margin_used > 0 and unrealized_pnl is not None:
        return (unrealized_pnl / margin_used) * 100
    return None


def calculate_realized_pnl(
    entry_price: float,
    exit_price: float,
    size: float,
    side: str = 'long'
) -> float:
    """
    计算已实现盈亏（根据持仓方向）

    Args:
        entry_price: 开仓价格
        exit_price: 平仓价格
        size: 平仓数量
        side: 持仓方向 'long' 或 'short'

    Returns:
        已实现盈亏
    """
    if side == 'long':
        return (exit_price - entry_price) * size
    else:
        return (entry_price - exit_price) * size


def calculate_pnl_percentage_from_prices(
    entry_price: float,
    exit_price: float,
    size: float,
    leverage: int = 1,
    side: str = 'long'
) -> float:
    """
    根据价格计算盈亏百分比

    Args:
        entry_price: 开仓价格
        exit_price: 平仓价格
        size: 持仓数量
        leverage: 杠杆倍数
        side: 持仓方向

    Returns:
        盈亏百分比
    """
    if entry_price <= 0 or size <= 0:
        return 0

    leverage = leverage or 1
    if leverage <= 0:
        leverage = 1

    realized_pnl = calculate_realized_pnl(entry_price, exit_price, size, side)
    return (realized_pnl / (entry_price * size)) * leverage * 100
