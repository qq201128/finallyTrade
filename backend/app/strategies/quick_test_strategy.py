"""
快速测试策略 - 用于测试交易系统功能
策略逻辑：
- 只要有数据就买入（快速开仓）
- 盈利1%或亏损1%就平仓（快速测试）
- 使用简单的移动平均线作为参考
"""


def populate_indicators(dataframe, metadata):
    """
    填充指标数据
    
    Args:
        dataframe: pandas DataFrame，包含OHLCV数据
        metadata: 元数据
    
    Returns:
        dataframe: 添加了指标后的DataFrame
    """
    # 计算简单的移动平均线（用于参考，不是交易信号）
    dataframe['sma_5'] = dataframe['close'].rolling(window=5).mean()
    dataframe['sma_10'] = dataframe['close'].rolling(window=10).mean()
    
    # 计算价格变化率
    dataframe['price_change'] = dataframe['close'].pct_change()
    
    return dataframe


def populate_entry_trend(dataframe, metadata):
    """
    填充入场信号
    
    策略：只要有足够的数据就买入（快速开仓测试）
    
    Args:
        dataframe: 包含指标的DataFrame
        metadata: 元数据
    
    Returns:
        Series: 入场信号，True表示买入信号
    """
    # 简单条件：只要有数据且价格存在就买入
    # 为了快速测试，我们设置一个非常简单的条件
    # 例如：价格大于0（总是满足）或者有足够的数据点
    
    # 确保有足够的数据点（至少10个）
    has_enough_data = len(dataframe) >= 10
    
    # 价格存在且有效
    price_valid = dataframe['close'].notna() & (dataframe['close'] > 0)
    
    # 简单的买入条件：有数据就买入（用于快速测试）
    # 在实际使用中，你可能想要更严格的条件
    entry_signal = has_enough_data & price_valid
    
    return entry_signal


def populate_exit_trend(dataframe, metadata):
    """
    填充出场信号
    
    策略：价格下跌超过1%就卖出（快速平仓测试）
    
    Args:
        dataframe: 包含指标的DataFrame
        metadata: 元数据
    
    Returns:
        Series: 出场信号，True表示卖出信号
    """
    # 计算价格变化
    price_change = dataframe['close'].pct_change()
    
    # 如果价格下跌超过1%，卖出
    exit_signal = price_change < -0.01
    
    return exit_signal


def before_loop(symbols):
    """
    循环开始前的回调函数
    
    Args:
        symbols: 可交易对列表
    """
    print(f"[快速测试策略] 开始交易循环，可交易对数量: {len(symbols)}")
    print(f"[快速测试策略] 交易对列表: {symbols[:10]}...")  # 只显示前10个


def after_loop(symbols):
    """
    循环结束后的回调函数
    
    Args:
        symbols: 可交易对列表
    """
    print(f"[快速测试策略] 交易循环结束")


def order_filled(order, exchange_order):
    """
    订单成交回调函数
    
    Args:
        order: 订单对象
        exchange_order: 交易所返回的订单信息
    """
    print(f"[快速测试策略] 订单 {order.id} 已成交: {exchange_order.get('symbol')}, "
          f"数量: {exchange_order.get('filled')}, 价格: {exchange_order.get('price')}")


def entry_conditions(symbol, analysis_result):
    """
    入场条件检查（额外验证）
    
    Args:
        symbol: 交易对
        analysis_result: 策略分析结果
    
    Returns:
        bool: 是否满足入场条件
    """
    # 快速测试：总是允许入场
    # 在实际使用中，你可能想要添加更多检查
    return True


def custom_exit(position, current_price):
    """
    自定义退出逻辑
    
    策略：快速止盈止损（盈利1%或亏损1%就退出）
    
    Args:
        position: 持仓对象
        current_price: 当前价格
    
    Returns:
        dict或None: 如果返回dict，包含{'price': float, 'reason': str}，表示应该退出
    """
    # 计算盈亏比例
    if position.entry_price and position.entry_price > 0:
        roi = (current_price - position.entry_price) / position.entry_price
        
        # 快速止盈：盈利超过1%就退出
        if roi > 0.01:
            return {
                'price': current_price,
                'reason': 'quick_profit',
                'roi': roi
            }
        
        # 快速止损：亏损超过1%就退出
        if roi < -0.01:
            return {
                'price': current_price,
                'reason': 'quick_stop_loss',
                'roi': roi
            }
    
    return None


def adjust_position(position):
    """
    仓位调整逻辑
    
    Args:
        position: 持仓对象
    
    Returns:
        dict: 包含{'should_adjust': bool, 'amount': float}
    """
    # 快速测试策略：不进行仓位调整
    return {'should_adjust': False, 'amount': 0}

