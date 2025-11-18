"""
使用 TA-Lib 的示例策略
展示如何使用技术指标进行交易决策

策略逻辑：
- 使用 MACD 和 RSI 指标
- MACD 金叉且 RSI < 70 时买入
- MACD 死叉或 RSI > 80 时卖出
- 设置止损和止盈
"""
import talib
import numpy as np


def populate_indicators(dataframe, metadata):
    """
    填充指标数据
    
    Args:
        dataframe: pandas DataFrame，包含OHLCV数据（列：open, high, low, close, volume）
        metadata: 元数据，包含交易对信息等
    
    Returns:
        dataframe: 添加了指标后的DataFrame
    """
    # 确保数据是 numpy array 格式（talib 需要）
    close = dataframe['close'].values.astype(np.float64)
    high = dataframe['high'].values.astype(np.float64)
    low = dataframe['low'].values.astype(np.float64)
    open_price = dataframe['open'].values.astype(np.float64)
    volume = dataframe['volume'].values.astype(np.float64)
    
    # ========== 趋势指标 ==========
    
    # MACD 指标
    macd, macd_signal, macd_hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    dataframe['macd'] = macd
    dataframe['macd_signal'] = macd_signal
    dataframe['macd_hist'] = macd_hist
    
    # EMA 均线
    dataframe['ema_12'] = talib.EMA(close, timeperiod=12)
    dataframe['ema_26'] = talib.EMA(close, timeperiod=26)
    dataframe['ema_50'] = talib.EMA(close, timeperiod=50)
    
    # SMA 均线
    dataframe['sma_20'] = talib.SMA(close, timeperiod=20)
    dataframe['sma_50'] = talib.SMA(close, timeperiod=50)
    
    # ========== 动量指标 ==========
    
    # RSI 相对强弱指标
    dataframe['rsi'] = talib.RSI(close, timeperiod=14)
    
    # Stochastic 随机指标
    slowk, slowd = talib.STOCH(high, low, close, 
                                fastk_period=14, 
                                slowk_period=3, 
                                slowd_period=3)
    dataframe['stoch_k'] = slowk
    dataframe['stoch_d'] = slowd
    
    # CCI 商品通道指标
    dataframe['cci'] = talib.CCI(high, low, close, timeperiod=14)
    
    # ========== 波动性指标 ==========
    
    # ATR 平均真实波幅
    dataframe['atr'] = talib.ATR(high, low, close, timeperiod=14)
    
    # Bollinger Bands 布林带
    upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
    dataframe['bb_upper'] = upper
    dataframe['bb_middle'] = middle
    dataframe['bb_lower'] = lower
    
    # ========== 成交量指标 ==========
    
    # OBV 能量潮
    dataframe['obv'] = talib.OBV(close, volume)
    
    # AD 累积/派发线
    dataframe['ad'] = talib.AD(high, low, close, volume)
    
    # ========== 形态识别 ==========
    
    # 识别看涨/看跌形态（可选）
    # dataframe['engulfing'] = talib.CDLENGULFING(open_price, high, low, close)
    # dataframe['hammer'] = talib.CDLHAMMER(open_price, high, low, close)
    # dataframe['doji'] = talib.CDLDOJI(open_price, high, low, close)
    
    return dataframe


def populate_entry_trend(dataframe, metadata):
    """
    填充入场信号
    
    策略：MACD 金叉 + RSI < 70 + 价格在 EMA12 上方
    
    Args:
        dataframe: 包含指标的DataFrame
        metadata: 元数据
    
    Returns:
        Series: 入场信号，True表示买入信号
    """
    conditions = []
    
    # 条件1: MACD 金叉（MACD 线上穿信号线）
    macd_cross_up = (
        (dataframe['macd'] > dataframe['macd_signal']) &
        (dataframe['macd'].shift(1) <= dataframe['macd_signal'].shift(1))
    )
    conditions.append(macd_cross_up)
    
    # 条件2: RSI < 70（避免超买）
    rsi_ok = dataframe['rsi'] < 70
    conditions.append(rsi_ok)
    
    # 条件3: 价格在 EMA12 上方（趋势向上）
    price_above_ema = dataframe['close'] > dataframe['ema_12']
    conditions.append(price_above_ema)
    
    # 条件4: 成交量增加（可选，确认趋势）
    volume_increase = dataframe['volume'] > dataframe['volume'].rolling(window=5).mean()
    conditions.append(volume_increase)
    
    # 条件5: MACD 柱状图为正（动量向上）
    macd_positive = dataframe['macd_hist'] > 0
    conditions.append(macd_positive)
    
    # 所有条件都满足时买入
    entry_signal = conditions[0]
    for condition in conditions[1:]:
        entry_signal = entry_signal & condition
    
    return entry_signal


def populate_exit_trend(dataframe, metadata):
    """
    填充出场信号
    
    策略：MACD 死叉 或 RSI > 80 或价格跌破 EMA12
    
    Args:
        dataframe: 包含指标的DataFrame
        metadata: 元数据
    
    Returns:
        Series: 出场信号，True表示卖出信号
    """
    conditions = []
    
    # 条件1: MACD 死叉（MACD 线下穿信号线）
    macd_cross_down = (
        (dataframe['macd'] < dataframe['macd_signal']) &
        (dataframe['macd'].shift(1) >= dataframe['macd_signal'].shift(1))
    )
    conditions.append(macd_cross_down)
    
    # 条件2: RSI > 80（超买）
    rsi_overbought = dataframe['rsi'] > 80
    conditions.append(rsi_overbought)
    
    # 条件3: 价格跌破 EMA12（趋势转弱）
    price_below_ema = dataframe['close'] < dataframe['ema_12']
    conditions.append(price_below_ema)
    
    # 条件4: MACD 柱状图为负（动量向下）
    macd_negative = dataframe['macd_hist'] < 0
    conditions.append(macd_negative)
    
    # 任一条件满足时卖出
    exit_signal = conditions[0]
    for condition in conditions[1:]:
        exit_signal = exit_signal | condition
    
    return exit_signal


def before_loop(symbols):
    """
    循环开始前的回调函数
    用于执行与货币对无关的计算、加载外部数据等
    
    Args:
        symbols: 可交易对列表
    """
    print(f"[TA-Lib策略] 开始交易循环，可交易对数量: {len(symbols)}")
    print(f"[TA-Lib策略] 交易对列表: {symbols[:5]}...")  # 只显示前5个


def after_loop(symbols):
    """
    循环结束后的回调函数
    
    Args:
        symbols: 可交易对列表
    """
    print(f"[TA-Lib策略] 交易循环结束")


def order_filled(order, exchange_order):
    """
    订单成交回调函数
    
    Args:
        order: 订单对象
        exchange_order: 交易所返回的订单信息
    """
    print(f"[TA-Lib策略] 订单 {order.id} 已成交: {exchange_order.get('symbol')}, "
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
    # 可以在这里添加额外的入场条件检查
    # 例如：检查市场波动性、检查持仓数量限制等
    return True


def custom_exit(position, current_price):
    """
    自定义退出逻辑
    
    策略：使用 ATR 设置动态止损
    
    Args:
        position: 持仓对象
        current_price: 当前价格
    
    Returns:
        dict或None: 如果返回dict，包含{'price': float}，表示应该退出
    """
    # 计算盈亏比例
    roi = (current_price - position.entry_price) / position.entry_price
    
    # 如果盈利超过 10%，考虑止盈
    if roi > 0.10:
        # 可以设置移动止盈，例如：如果盈利回撤超过 5%，则退出
        max_profit = getattr(position, '_max_profit', roi)
        if roi > max_profit:
            position._max_profit = roi
        
        # 如果从最高盈利回撤超过 5%，止盈
        if max_profit - roi > 0.05:
            return {'price': current_price, 'reason': 'trailing_stop'}
    
    # 如果亏损超过 5%，止损
    if roi < -0.05:
        return {'price': current_price, 'reason': 'stop_loss'}
    
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
    # 如果需要，可以在这里实现加仓或减仓逻辑
    return {'should_adjust': False, 'amount': 0}

