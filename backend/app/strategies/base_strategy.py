"""
策略基类 - 提供公共方法的默认实现

策略可以通过继承此基类来复用公共方法，也可以选择重写特定方法。
如果策略不继承基类，仍然可以正常工作（向后兼容）。
"""
import logging
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """
    策略基类
    
    提供以下公共方法的默认实现：
    - before_loop: 循环开始前的回调
    - after_loop: 循环结束后的回调
    - order_filled: 订单成交回调
    - entry_conditions: 入场条件检查
    - custom_exit: 自定义退出逻辑（可选）
    - adjust_position: 仓位调整逻辑（可选）
    
    策略可以继承此基类，然后：
    1. 使用默认实现（不需要重写）
    2. 重写特定方法以自定义行为
    3. 在模块级别导出需要的方法为函数
    """
    
    def before_loop(self, symbols: List[str]) -> None:
        """
        循环开始前的回调函数
        
        Args:
            symbols: 可交易对列表
        """
        logger.info(f"[策略] 开始交易循环，可交易对数量: {len(symbols)}")
    
    def after_loop(self, symbols: List[str]) -> None:
        """
        循环结束后的回调函数
        
        Args:
            symbols: 可交易对列表
        """
        logger.info(f"[策略] 交易循环结束")
    
    def order_filled(self, order, exchange_order: Dict[str, Any]) -> None:
        """
        订单成交回调函数
        
        Args:
            order: 订单对象
            exchange_order: 交易所返回的订单信息
        """
        symbol = exchange_order.get('symbol', '')
        price = exchange_order.get('price', 0)
        filled = exchange_order.get('filled', 0)
        logger.info(f"[策略] 订单 {getattr(order, 'id', 'N/A')} 已成交: {symbol}, "
                   f"方向: {getattr(order, 'side', 'N/A')}, 数量: {filled}, 价格: {price}")
    
    def entry_conditions(self, symbol: str, analysis_result: Dict[str, Any]) -> bool:
        """
        入场条件检查
        
        Args:
            symbol: 交易对
            analysis_result: 策略分析结果
        
        Returns:
            bool: 是否满足入场条件（默认返回 True，允许入场）
        """
        return True
    
    def custom_exit(self, position, current_price: float) -> Optional[Dict[str, Any]]:
        """
        自定义退出逻辑（可选）
        
        Args:
            position: 持仓对象
            current_price: 当前价格
        
        Returns:
            dict或None: 如果返回dict，包含退出信息
                - price: 退出价格
                - reason: 退出原因
                - reduce_percent: 平仓比例（0.0-1.0）
                - close_amount: 平仓数量（可选）
        """
        return None
    
    def adjust_position(self, position) -> Dict[str, Any]:
        """
        仓位调整逻辑（可选）
        
        Args:
            position: 持仓对象
        
        Returns:
            dict: 包含 {'should_adjust': bool, 'amount': float}
        """
        return {'should_adjust': False, 'amount': 0}
    
    @classmethod
    def export_to_module(cls, strategy_instance: 'BaseStrategy', module: Any) -> None:
        """
        将策略实例的方法导出到模块级别，以便策略引擎可以找到它们
        
        Args:
            strategy_instance: 策略实例
            module: 策略模块对象
        """
        # 导出公共回调方法
        if hasattr(strategy_instance, 'before_loop'):
            module.before_loop = strategy_instance.before_loop
        if hasattr(strategy_instance, 'after_loop'):
            module.after_loop = strategy_instance.after_loop
        if hasattr(strategy_instance, 'order_filled'):
            module.order_filled = strategy_instance.order_filled
        if hasattr(strategy_instance, 'entry_conditions'):
            module.entry_conditions = strategy_instance.entry_conditions
        if hasattr(strategy_instance, 'custom_exit'):
            module.custom_exit = strategy_instance.custom_exit
        if hasattr(strategy_instance, 'adjust_position'):
            module.adjust_position = strategy_instance.adjust_position

