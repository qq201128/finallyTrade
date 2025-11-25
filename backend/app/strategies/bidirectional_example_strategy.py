"""
双向交易示例策略（动态补仓版本）

策略特点：
- 入场信号完全对称，满足基础条件即可在任意时刻入场
- 单笔持仓盈利超过保证金50%时立即平仓
- 亏损时不平仓，通过补仓机制处理（每方向累计4次盈利后，为另一方向提供1次亏损补仓机会）
- 每增加4次盈利，补仓次数+1，补仓数量为对应盈利持仓开仓量的一半
- 趋势出现反转（盈利转亏或亏转盈）时，自动清空所有统计与补仓机会

注意：使用此策略需要在前端配置中开启"双向交易"选项。
"""
import talib
import numpy as np
import pandas as pd
from app.strategies.base_strategy import BaseStrategy

def _get_strategy_state(user_strategy):
    """从数据库配置中获取策略状态，如果不存在则初始化"""
    if not user_strategy.config:
        user_strategy.config = {}
    
    if 'replenish_state' not in user_strategy.config:
        user_strategy.config['replenish_state'] = {
    'long': {
        'wins': 0,
        'last_trend': None,
        'replenish_pool': []
    },
    'short': {
        'wins': 0,
        'last_trend': None,
        'replenish_pool': []
    }
}

    return user_strategy.config['replenish_state']


def _save_strategy_state(user_strategy, db):
    """保存策略状态到数据库"""
    try:
        db.commit()
    except Exception as e:
        print(f"[错误] 保存策略状态失败: {e}")
        db.rollback()


def _reset_state(user_strategy, db):
    """重置策略状态"""
    state = _get_strategy_state(user_strategy)
    for side in state.keys():
        state[side]['wins'] = 0
        state[side]['last_trend'] = None
        state[side]['replenish_pool'] = []
    _save_strategy_state(user_strategy, db)


def _record_win(side: str, position_size: float, user_strategy, db):
    """记录方向盈利，用于生成补仓机会"""
    state = _get_strategy_state(user_strategy)
    state[side]['wins'] = state[side].get('wins', 0) + 1
    if state[side]['wins'] % 4 == 0 and position_size:
        opposite = 'short' if side == 'long' else 'long'
        replenish_amount = max(position_size * 0.5, 0)
        if replenish_amount > 0:
            if 'replenish_pool' not in state[opposite]:
                state[opposite]['replenish_pool'] = []
            state[opposite]['replenish_pool'].append(replenish_amount)
            _save_strategy_state(user_strategy, db)


def _update_trend_state(side: str, roi: float, user_strategy, db):
    """监控趋势反转：盈利 -> 亏损 或 亏损 -> 盈利"""
    if roi is None:
        return
    state = _get_strategy_state(user_strategy)
    if roi > 0:
        trend = 'profit'
    elif roi < 0:
        trend = 'loss'
    else:
        trend = 'flat'
    last = state[side].get('last_trend')
    if last and trend in ('profit', 'loss') and trend != last:
        _reset_state(user_strategy, db)
        state = _get_strategy_state(user_strategy)  # 重新获取重置后的状态
    if trend in ('profit', 'loss'):
        state[side]['last_trend'] = trend
        _save_strategy_state(user_strategy, db)

def populate_indicators(dataframe, metadata):
    """
    填充指标数据
    
    Args:
        dataframe: pandas DataFrame，包含OHLCV数据
        metadata: 元数据
    
    Returns:
        dataframe: 添加了指标后的DataFrame
    """
    close = dataframe['close'].values.astype(np.float64)
    high = dataframe['high'].values.astype(np.float64)
    low = dataframe['low'].values.astype(np.float64)
    volume = dataframe['volume'].values.astype(np.float64)
    
    # RSI指标
    dataframe['rsi'] = talib.RSI(close, timeperiod=14)
    dataframe['rsi_prev'] = dataframe['rsi'].shift(1)
    
    # EMA均线
    dataframe['ema_12'] = talib.EMA(close, timeperiod=12)
    dataframe['ema_26'] = talib.EMA(close, timeperiod=26)
    dataframe['ema_50'] = talib.EMA(close, timeperiod=50)
    
    # MACD指标
    macd, macd_signal, macd_hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    dataframe['macd'] = macd
    dataframe['macd_signal'] = macd_signal
    dataframe['macd_hist'] = macd_hist
    
    # ATR指标
    dataframe['atr'] = talib.ATR(high, low, close, timeperiod=14)
    
    # 成交量指标
    dataframe['volume_ma'] = dataframe['volume'].rolling(window=20).mean()
    dataframe['volume_ratio'] = dataframe['volume'] / dataframe['volume_ma']
    
    return dataframe


def populate_entry_trend_long(dataframe, metadata):
    """
    Long 入场信号：保持与 Short 一致，始终允许入场
    """
    return pd.Series(True, index=dataframe.index)


def populate_entry_trend_short(dataframe, metadata):
    """
    Short 入场信号：保持与 Long 一致，始终允许入场
    """
    return pd.Series(True, index=dataframe.index)


def populate_exit_trend_long(dataframe, metadata):
    """出场逻辑由 custom_exit 控制，此处返回 False 序列。"""
    return pd.Series(False, index=dataframe.index)


def populate_exit_trend_short(dataframe, metadata):
    """出场逻辑由 custom_exit 控制，此处返回 False 序列。"""
    return pd.Series(False, index=dataframe.index)


class BidirectionalExampleStrategy(BaseStrategy):
    """
    双向交易示例策略类
    继承 BaseStrategy 以复用公共方法
    """
    
    # def before_loop(self, symbols):
    #     """重写基类方法，添加策略特定的日志"""
    #     print(f"[双向交易策略] 开始交易循环，可交易对数量: {len(symbols)}")
    
    # def after_loop(self, symbols):
    #     """重写基类方法，添加策略特定的日志"""
    #     print(f"[双向交易策略] 交易循环结束")
    
    # def order_filled(self, order, exchange_order):
    #     """重写基类方法，添加策略特定的日志"""
    #     print(f"[双向交易策略] 订单 {order.id} 已成交: {exchange_order.get('symbol')}, "
    #           f"方向: {order.side}, 数量: {exchange_order.get('filled')}, 价格: {exchange_order.get('price')}")
    
    def custom_exit(self, position, current_price, db=None, user_strategy=None):
        """
        自定义退出逻辑（支持双向）
        
        策略：
        - Long持仓：盈利超过保证金50%时退出（亏损时通过补仓处理，不平仓）
        - Short持仓：盈利超过保证金50%时退出（亏损时通过补仓处理，不平仓）
        
        Args:
            position: 持仓对象
            current_price: 当前价格
            db: 数据库会话（可选，用于持久化状态）
            user_strategy: 用户策略对象（可选，用于持久化状态）
        
        Returns:
            dict或None: 如果返回dict，包含退出信息
        """
        if not position or not position.entry_price or position.entry_price <= 0 or not current_price:
            return None
        
        # 获取 user_strategy 和 db（如果未传递）
        if not user_strategy and hasattr(position, 'user_strategy'):
            user_strategy = position.user_strategy
        if not db and user_strategy and hasattr(user_strategy, '_sa_instance_state'):
            # 尝试从 user_strategy 获取数据库会话
            from sqlalchemy.orm import object_session
            db = object_session(user_strategy) if user_strategy else None
        
        # 计算盈亏比例（根据持仓方向）
        if position.side == 'long':
            roi = (current_price - position.entry_price) / position.entry_price
        else:
            roi = (position.entry_price - current_price) / position.entry_price
        
        if user_strategy and db:
            _update_trend_state(position.side, roi, user_strategy, db)
        
        # 计算杠杆后的盈亏百分比（基于保证金）
        leverage = getattr(position, 'leverage', 1) or 1
        if leverage <= 0:
            leverage = 1
        
        # 计算保证金
        position_size = abs(position.size or 0)
        margin_used = (position.entry_price * position_size) / leverage
        
        # 计算基于保证金的盈亏百分比
        # 优先使用已计算的 unrealized_pnl
        unrealized_pnl = getattr(position, 'unrealized_pnl', None)
        if unrealized_pnl is None:
            # 如果 unrealized_pnl 未设置，手动计算
            if position.side == 'long':
                unrealized_pnl = (current_price - position.entry_price) * position_size
            else:
                unrealized_pnl = (position.entry_price - current_price) * position_size
        
        if margin_used > 0:
            pnl_percentage = (unrealized_pnl / margin_used) * 100
        else:
            # 如果无法计算保证金，使用价格变动计算
            pnl_percentage = roi * leverage * 100
        
        # 注意：亏损时不平仓，通过 adjust_position 进行补仓处理
        
        # 止盈：盈利超过保证金50%时平仓（考虑杠杆）
        if pnl_percentage >= 50:
            if user_strategy and db:
                _record_win(position.side, position.size, user_strategy, db)
            return {
                'price': current_price,
                'reason': 'take_profit_50pct',
                'reduce_percent': 1.0  # 全部平仓
            }
        
        return None
    
    def adjust_position(self, position, db=None, user_strategy=None):
        """
        仓位调整逻辑（支持双向补仓）
        
        策略：
        - 每方向盈利平仓4次后，为另一方向提供1次亏损补仓机会
        - 补仓仅在持仓亏损且存在补仓额度时执行
        - 补仓数量为对应盈利持仓开仓量的一半
        
        Args:
            position: 持仓对象
            db: 数据库会话（可选，用于持久化状态）
            user_strategy: 用户策略对象（可选，用于持久化状态）
        
        Returns:
            dict: 包含{'should_adjust': bool, 'amount': float}
        """
        if not position or not position.entry_price or position.entry_price <= 0:
            return {'should_adjust': False, 'amount': 0}
        
        current_price = position.current_price
        if current_price is None or current_price <= 0:
            return {'should_adjust': False, 'amount': 0}
        
        # 获取 user_strategy 和 db（如果未传递）
        if not user_strategy and hasattr(position, 'user_strategy'):
            user_strategy = position.user_strategy
        if not db and user_strategy and hasattr(user_strategy, '_sa_instance_state'):
            # 尝试从 user_strategy 获取数据库会话
            from sqlalchemy.orm import object_session
            db = object_session(user_strategy) if user_strategy else None
        
        if position.side == 'long':
            roi = (current_price - position.entry_price) / position.entry_price
        else:
            roi = (position.entry_price - current_price) / position.entry_price
        
        if user_strategy and db:
            _update_trend_state(position.side, roi, user_strategy, db)
        
        # 仅在亏损且存在补仓额度时执行
        if user_strategy:
            state = _get_strategy_state(user_strategy)
            replenish_pool = state[position.side].get('replenish_pool', [])
            if roi < 0 and replenish_pool:
                amount = replenish_pool.pop(0)
                amount = max(amount, 0)
                if amount > 0:
                    _save_strategy_state(user_strategy, db)
                    return {
                        'should_adjust': True,
                        'amount': amount
                    }
        
        return {'should_adjust': False, 'amount': 0}


# 创建策略实例（策略引擎会自动从实例中获取方法，无需手动导出）
# 注意：实例名不能以下划线开头，否则策略引擎会跳过
strategy_instance = BidirectionalExampleStrategy()

# 可选：如果希望明确导出到模块级别（更高效，但非必需）
# 策略引擎会优先从 BaseStrategy 实例获取方法，如果找不到才会查找模块级别
# before_loop = strategy_instance.before_loop
# after_loop = strategy_instance.after_loop
# order_filled = strategy_instance.order_filled
# entry_conditions = strategy_instance.entry_conditions
# custom_exit = strategy_instance.custom_exit
# adjust_position = strategy_instance.adjust_position

