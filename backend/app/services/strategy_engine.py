"""
策略引擎 - 动态加载和执行策略
"""
import importlib.util
import os
import sys
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
import logging

# 尝试导入 pandas，用于检查 Series 类型
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

logger = logging.getLogger(__name__)


class StrategyEngine:
    """策略引擎类"""
    
    def __init__(self, strategies_dir: str):
        """
        初始化策略引擎
        
        Args:
            strategies_dir: 策略文件目录
        """
        self.strategies_dir = Path(strategies_dir)
        self.strategies_dir.mkdir(parents=True, exist_ok=True)
        self.loaded_strategies: Dict[str, Any] = {}
    
    def load_strategy(self, strategy_name: str, file_path: str) -> Any:
        """
        动态加载策略模块
        
        Args:
            strategy_name: 策略名称
            file_path: 策略文件路径
        """
        if strategy_name in self.loaded_strategies:
            return self.loaded_strategies[strategy_name]
        
        try:
            spec = importlib.util.spec_from_file_location(strategy_name, file_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"无法加载策略文件: {file_path}")
            
            module = importlib.util.module_from_spec(spec)
            sys.modules[strategy_name] = module
            spec.loader.exec_module(module)
            
            self.loaded_strategies[strategy_name] = module
            logger.info(f"策略 {strategy_name} 加载成功")
            return module
        except Exception as e:
            logger.error(f"加载策略 {strategy_name} 失败: {e}")
            raise
    
    def reload_strategy(self, strategy_name: str, file_path: str) -> Any:
        """重新加载策略"""
        if strategy_name in self.loaded_strategies:
            del self.loaded_strategies[strategy_name]
            if strategy_name in sys.modules:
                del sys.modules[strategy_name]
        
        return self.load_strategy(strategy_name, file_path)
    
    def get_strategy_function(self, strategy_module: Any, function_name: str) -> Optional[Callable]:
        """
        获取策略函数
        
        支持两种方式（按优先级）：
        1. 从 BaseStrategy 基类实例中获取方法（如果策略继承基类，优先使用）
        2. 模块级别的函数（传统方式，向后兼容）
        
        Args:
            strategy_module: 策略模块
            function_name: 函数名，如 'populate_indicators', 'populate_entry_trend', 'populate_exit_trend'
        """
        # 首先尝试从 BaseStrategy 实例获取（如果策略使用继承方式）
        # 查找模块中是否有 BaseStrategy 的实例（通过检查类名避免循环导入）
        try:
            # 优先检查常见的实例名（包括带下划线的，用于兼容性）
            common_instance_names = ['strategy_instance', '_strategy_instance']
            for instance_name in common_instance_names:
                if hasattr(strategy_module, instance_name):
                    attr = getattr(strategy_module, instance_name)
                    if hasattr(attr, '__class__'):
                        class_name = attr.__class__.__name__
                        # 检查类名或基类名是否为 BaseStrategy
                        if class_name == 'BaseStrategy' or any(
                            base.__name__ == 'BaseStrategy' 
                            for base in attr.__class__.__mro__ 
                            if hasattr(base, '__name__')
                        ):
                            method = getattr(attr, function_name, None)
                            if method is not None and callable(method):
                                return method
            
            # 如果常见实例名没找到，遍历所有属性（跳过私有属性，但允许 _strategy_instance）
            for attr_name in dir(strategy_module):
                if attr_name.startswith('_') and attr_name != '_strategy_instance':
                    continue
                attr = getattr(strategy_module, attr_name)
                # 检查是否是 BaseStrategy 的实例（通过类名检查，避免导入）
                if hasattr(attr, '__class__'):
                    class_name = attr.__class__.__name__
                    # 检查类名或基类名是否为 BaseStrategy
                    if class_name == 'BaseStrategy' or any(
                        base.__name__ == 'BaseStrategy' 
                        for base in attr.__class__.__mro__ 
                        if hasattr(base, '__name__')
                    ):
                        method = getattr(attr, function_name, None)
                        if method is not None and callable(method):
                            return method
        except Exception as e:
            logger.debug(f"从基类获取方法时出错: {e}")
        
        # 如果从 BaseStrategy 实例没找到，尝试从模块级别获取（传统方式，向后兼容）
        func = getattr(strategy_module, function_name, None)
        if func is not None:
            return func
        
        return None
    
    def call_strategy_callback(self, strategy_module: Any, callback_name: str, *args, **kwargs) -> Any:
        """
        调用策略回调函数
        
        Args:
            strategy_module: 策略模块
            callback_name: 回调函数名
            *args, **kwargs: 回调函数参数
        """
        callback = self.get_strategy_function(strategy_module, callback_name)
        if callback:
            try:
                return callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"调用策略回调 {callback_name} 失败: {e}", exc_info=True)
                return None
        return None
    
    def populate_indicators(self, strategy_module: Any, dataframe: Any, metadata: Dict) -> Any:
        """
        填充指标数据
        
        Args:
            strategy_module: 策略模块
            dataframe: 数据框（通常是pandas DataFrame或类似结构）
            metadata: 元数据，包含交易对信息等
        """
        populate_func = self.get_strategy_function(strategy_module, 'populate_indicators')
        if populate_func:
            try:
                return populate_func(dataframe, metadata)
            except Exception as e:
                logger.error(f"填充指标失败: {e}")
                return dataframe
        return dataframe
    
    def check_entry_signal(
        self,
        strategy_module: Any,
        dataframe: Any,
        metadata: Dict,
        function_name: str = 'populate_entry_trend'
    ) -> bool:
        """
        检查入场信号
        
        Args:
            strategy_module: 策略模块
            dataframe: 数据框
            metadata: 元数据
            function_name: 策略函数名称，默认使用 `populate_entry_trend`
        """
        entry_func = self.get_strategy_function(strategy_module, function_name)
        if entry_func:
            try:
                # 通常返回一个布尔值或Series，表示是否有入场信号
                result = entry_func(dataframe, metadata)
                
                # 检查是否是 pandas Series
                if HAS_PANDAS and isinstance(result, pd.Series):
                    # 如果是 Series，取最后一个值（最新的信号）
                    if len(result) > 0:
                        return bool(result.iloc[-1])
                    return False
                
                # 检查是否是其他可迭代对象（但不是字符串）
                if hasattr(result, '__iter__') and not isinstance(result, str):
                    try:
                        result_list = list(result)
                        if len(result_list) > 0:
                            return bool(result_list[-1])
                        return False
                    except (TypeError, ValueError):
                        # 如果无法转换为列表，尝试直接转换
                        pass
                
                # 如果是单个值，直接转换为布尔值
                return bool(result)
            except Exception as e:
                logger.error(f"检查入场信号失败: {e}")
                return False
        return False
    
    def check_exit_signal(
        self,
        strategy_module: Any,
        dataframe: Any,
        metadata: Dict,
        function_name: str = 'populate_exit_trend'
    ) -> bool:
        """
        检查出场信号
        
        Args:
            strategy_module: 策略模块
            dataframe: 数据框
            metadata: 元数据
            function_name: 策略函数名称，默认使用 `populate_exit_trend`
        """
        exit_func = self.get_strategy_function(strategy_module, function_name)
        if exit_func:
            try:
                result = exit_func(dataframe, metadata)
                
                # 检查是否是 pandas Series
                if HAS_PANDAS and isinstance(result, pd.Series):
                    # 如果是 Series，取最后一个值（最新的信号）
                    if len(result) > 0:
                        return bool(result.iloc[-1])
                    return False
                
                # 检查是否是其他可迭代对象（但不是字符串）
                if hasattr(result, '__iter__') and not isinstance(result, str):
                    try:
                        result_list = list(result)
                        if len(result_list) > 0:
                            return bool(result_list[-1])
                        return False
                    except (TypeError, ValueError):
                        # 如果无法转换为列表，尝试直接转换
                        pass
                
                # 如果是单个值，直接转换为布尔值
                return bool(result)
            except Exception as e:
                logger.error(f"检查出场信号失败: {e}")
                return False
        return False
    
    def get_strategy_list(self) -> List[str]:
        """获取策略文件列表"""
        strategies = []
        if self.strategies_dir.exists():
            for file in self.strategies_dir.glob("*.py"):
                if file.name != "__init__.py":
                    strategies.append(file.stem)
        return strategies

