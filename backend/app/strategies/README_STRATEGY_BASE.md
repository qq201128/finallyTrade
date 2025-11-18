# 策略基类使用指南

## 概述

`BaseStrategy` 基类提供了策略中公共方法的默认实现，通过继承可以简化策略代码，减少重复。

## 基类提供的公共方法

### 1. `before_loop(symbols: List[str]) -> None`
循环开始前的回调函数，默认实现会记录日志。

### 2. `after_loop(symbols: List[str]) -> None`
循环结束后的回调函数，默认实现会记录日志。

### 3. `order_filled(order, exchange_order: Dict[str, Any]) -> None`
订单成交回调函数，默认实现会记录订单信息。

### 4. `entry_conditions(symbol: str, analysis_result: Dict[str, Any]) -> bool`
入场条件检查，默认返回 `True`（允许入场）。

### 5. `custom_exit(position, current_price: float) -> Optional[Dict[str, Any]]`
自定义退出逻辑（可选），默认返回 `None`（不退出）。

### 6. `adjust_position(position) -> Dict[str, Any]`
仓位调整逻辑（可选），默认返回 `{'should_adjust': False, 'amount': 0}`（不调整）。

## 使用方式

### 方式一：继承基类（推荐）

```python
from app.strategies.base_strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    """我的策略类"""
    
    # 只重写需要自定义的方法
    def before_loop(self, symbols):
        """自定义循环开始前的逻辑"""
        print(f"[我的策略] 开始交易，交易对: {symbols}")
    
    # 其他方法使用基类的默认实现，或者重写
    def custom_exit(self, position, current_price):
        """自定义退出逻辑"""
        # 你的退出逻辑
        return None

# 创建策略实例
_strategy_instance = MyStrategy()

# 导出方法到模块级别（供策略引擎调用）
before_loop = _strategy_instance.before_loop
after_loop = _strategy_instance.after_loop
order_filled = _strategy_instance.order_filled
entry_conditions = _strategy_instance.entry_conditions
custom_exit = _strategy_instance.custom_exit
adjust_position = _strategy_instance.adjust_position

# 其他策略函数（populate_indicators, populate_entry_trend 等）直接定义在模块级别
def populate_indicators(dataframe, metadata):
    # 你的指标计算逻辑
    return dataframe
```

### 方式二：传统方式（向后兼容）

如果策略不继承基类，仍然可以正常工作：

```python
def before_loop(symbols):
    """循环开始前的回调"""
    print(f"开始交易循环，交易对数量: {len(symbols)}")

def after_loop(symbols):
    """循环结束后的回调"""
    print("交易循环结束")

# ... 其他函数
```

## 优势

1. **代码复用**：公共方法只需在基类中实现一次
2. **一致性**：所有策略使用相同的默认行为
3. **灵活性**：策略可以选择重写任何方法
4. **向后兼容**：不继承基类的策略仍然可以正常工作

## 示例

参考 `bidirectional_example_strategy.py` 查看完整示例。

