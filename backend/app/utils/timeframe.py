"""
时间周期解析工具模块
"""
import re
from datetime import datetime
from typing import Optional


def parse_timeframe(timeframe: str) -> int:
    """
    解析时间周期字符串，返回秒数

    Args:
        timeframe: 时间周期字符串，如 '1m', '5m', '1h', '1d'

    Returns:
        秒数
    """
    match = re.match(r'(\d+)([smhd])', timeframe.lower())
    if not match:
        return 3600  # 默认1小时

    value = int(match.group(1))
    unit = match.group(2)

    unit_multipliers = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400,
    }

    return value * unit_multipliers.get(unit, 3600)


def get_candle_start_timestamp(timestamp: datetime, timeframe: str) -> datetime:
    """
    获取K线周期的开始时间戳

    Args:
        timestamp: 时间戳
        timeframe: 时间周期字符串

    Returns:
        K线周期的开始时间戳
    """
    seconds = parse_timeframe(timeframe)
    unix_timestamp = int(timestamp.timestamp())
    candle_start = unix_timestamp // seconds * seconds
    return datetime.fromtimestamp(candle_start)
