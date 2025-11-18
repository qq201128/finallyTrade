"""
示例策略文件
用户可以参考此文件编写自己的策略
"""


def populate_indicators(dataframe, metadata):
    """
    填充指标数据
    
    Args:
        dataframe: pandas DataFrame，包含OHLCV数据
        metadata: 元数据，包含交易对信息等
    
    Returns:
        dataframe: 添加了指标后的DataFrame
    """
    # 示例：添加简单移动平均线
    dataframe['sma_20'] = dataframe['close'].rolling(window=20).mean()
    dataframe['sma_50'] = dataframe['close'].rolling(window=50).mean()
    
    # 示例：添加RSI指标
    delta = dataframe['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    dataframe['rsi'] = 100 - (100 / (1 + rs))
    
    return dataframe


def populate_entry_trend(dataframe, metadata):
    """
    填充入场信号
    
    Args:
        dataframe: 包含指标的DataFrame
        metadata: 元数据
    
    Returns:
        Series或bool: 入场信号，True表示买入信号
    """
    # 示例策略：金叉买入
    # 当短期均线上穿长期均线，且RSI < 70时买入
    conditions = (
        (dataframe['sma_20'] > dataframe['sma_50']) &
        (dataframe['sma_20'].shift(1) <= dataframe['sma_50'].shift(1)) &
        (dataframe['rsi'] < 70)
    )
    return conditions


def populate_exit_trend(dataframe, metadata):
    """
    填充出场信号
    
    Args:
        dataframe: 包含指标的DataFrame
        metadata: 元数据
    
    Returns:
        Series或bool: 出场信号，True表示卖出信号
    """
    # 示例策略：死叉卖出或RSI超买
    conditions = (
        (dataframe['sma_20'] < dataframe['sma_50']) &
        (dataframe['sma_20'].shift(1) >= dataframe['sma_50'].shift(1))
    ) | (dataframe['rsi'] > 80)
    return conditions


def before_loop(symbols):
    """
    循环开始前的回调函数
    用于执行与货币对无关的计算、加载外部数据等
    
    Args:
        symbols: 可交易对列表
    """
    print(f"开始交易循环，可交易对数量: {len(symbols)}")
    pass


def after_loop(symbols):
    """
    循环结束后的回调函数
    
    Args:
        symbols: 可交易对列表
    """
    print(f"交易循环结束")
    pass


def order_filled(order, exchange_order):
    """
    订单成交回调函数
    
    Args:
        order: 订单对象
        exchange_order: 交易所返回的订单信息
    """
    print(f"订单 {order.id} 已成交: {exchange_order}")
    pass


def entry_conditions(symbol, analysis_result):
    """
    入场条件检查
    
    Args:
        symbol: 交易对
        analysis_result: 策略分析结果
    
    Returns:
        bool: 是否满足入场条件
    """
    # 可以在这里添加额外的入场条件检查
    return True


def custom_exit(position, current_price):
    """
    自定义退出逻辑
    
    Args:
        position: 持仓对象
        current_price: 当前价格
    
    Returns:
        dict或None: 如果返回dict，包含{'price': float}，表示应该退出
    """
    # 示例：如果盈利超过20%，退出
    roi = (current_price - position.entry_price) / position.entry_price
    if roi > 0.2:
        return {'price': current_price}
    return None


def adjust_position(position):
    """
    仓位调整逻辑
    
    Args:
        position: 持仓对象
    
    Returns:
        dict: 包含{'should_adjust': bool, 'amount': float}
    """
    # 示例：不进行仓位调整
    return {'should_adjust': False, 'amount': 0}

