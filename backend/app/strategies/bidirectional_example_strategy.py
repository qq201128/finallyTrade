"""
双向交易示例策略（动态补仓版本）

策略特点：
- 入场信号完全对称，满足基础条件即可在任意时刻入场
- 单笔持仓盈利超过保证金50%时立即平仓
- 亏损时不平仓，通过补仓机制处理（每方向累计4次盈利后，为另一方向提供1次亏损补仓机会）
- 每增加4次盈利，补仓次数+1，补仓数量为对应盈利持仓开仓量的一半
- 趋势出现反转（盈利转亏或亏转盈）时，自动清空所有统计与补仓机会

补仓逻辑说明：
- 补仓额度单位是 USDT（保证金），不是币的数量
- 生成补仓额度：盈利平仓时，补仓额度 = 该笔持仓保证金 × 0.5
- 执行补仓：币数量 = 补仓额度(USDT) × 杠杆 / 当前价格

注意：使用此策略需要在前端配置中开启"双向交易"选项。
"""
import logging
import talib
import numpy as np
import pandas as pd
from app.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

def _get_strategy_state(user_strategy, db=None):
    """从数据库配置中获取策略状态，如果不存在则初始化

    Args:
        user_strategy: 用户策略对象
        db: 数据库会话（可选，用于刷新对象以获取最新数据）
    """
    if not user_strategy:
        return {
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

    # 关键修复：刷新 user_strategy 对象以获取数据库中的最新数据
    # 这解决了在同一会话中多次读写时，内存中对象与数据库不同步的问题
    if db:
        try:
            db.refresh(user_strategy)
        except Exception as e:
            logger.debug(f"刷新 user_strategy 失败: {e}")

    # 安全地访问 user_strategy.config
    try:
        config = user_strategy.config
    except Exception as e:
        # UserStrategy 对象已过期或已被删除
        logger.warning(f"无法访问 user_strategy.config，对象可能已过期: {e}")
        return {
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
    
    if not config:
        config = {}
        # 尝试设置 config（如果 user_strategy 仍然有效）
        try:
            user_strategy.config = config
        except Exception:
            # 如果无法设置，继续使用空字典
            pass
    
    if 'replenish_state' not in config:
        config['replenish_state'] = {
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
        # 尝试更新 user_strategy.config（如果仍然有效）
        try:
            user_strategy.config = config
        except Exception:
            # 如果无法更新，继续使用内存中的 config
            pass

    # 添加调试日志，显示从数据库读取的状态
    replenish_state = config['replenish_state']
    logger.info(f"[读取策略状态] 策略ID: {user_strategy.id if user_strategy else 'N/A'}, "
                f"long: wins={replenish_state['long'].get('wins', 0)}, "
                f"补仓池={replenish_state['long'].get('replenish_pool', [])}, "
                f"short: wins={replenish_state['short'].get('wins', 0)}, "
                f"补仓池={replenish_state['short'].get('replenish_pool', [])}")

    return replenish_state


def _save_strategy_state(user_strategy, db):
    """保存策略状态到数据库"""
    if not db:
        return
    
    # 检查数据库会话是否有效
    try:
        # 检查会话是否已关闭
        if db.is_active is False:
            logger.debug("数据库会话已关闭，无法保存策略状态")
            return
    except Exception:
        # 如果无法检查会话状态，尝试继续
        pass
    
    try:
        # 检查 user_strategy 是否仍然有效
        if user_strategy:
            try:
                strategy_id = user_strategy.id
            except Exception:
                logger.debug("user_strategy 已过期，无法保存策略状态")
                return
            
            # 确保 config 被正确设置
            if not user_strategy.config:
                user_strategy.config = {}
            
            # 关键修复：确保 SQLAlchemy 检测到 JSON 字段的修改
            # 需要显式标记 config 字段为已修改，否则 SQLAlchemy 可能不会保存
            from sqlalchemy.orm.attributes import flag_modified
            
            # 标记 config 字段为已修改（必须在修改后立即调用）
            flag_modified(user_strategy, 'config')
            
            logger.info(f"[保存策略状态] 策略ID: {strategy_id}, replenish_state: {user_strategy.config.get('replenish_state', {})}")
            
            # 先 flush 确保数据写入
            try:
                db.flush()
            except Exception as e:
                logger.warning(f"flush 策略状态失败: {e}，尝试 rollback 后重试")
                try:
                    if db.is_active:
                        db.rollback()
                        # 重新标记并重试
                        flag_modified(user_strategy, 'config')
                        db.flush()
                    else:
                        logger.warning("数据库会话已关闭，无法重试")
                        return
                except Exception as retry_error:
                    logger.error(f"重试 flush 也失败: {retry_error}")
                    # 不抛出异常，避免影响主流程
                    return
        
        # 提交事务（如果会话仍然有效）
        try:
            if db.is_active:
                db.commit()
                logger.debug(f"[保存策略状态] 成功保存到数据库")
            else:
                logger.warning("数据库会话已关闭，无法提交")
        except Exception as commit_error:
            logger.warning(f"commit 失败: {commit_error}")
            try:
                if db.is_active:
                    db.rollback()
            except Exception:
                pass
            # 不抛出异常，避免影响主流程
    except Exception as e:
        logger.warning(f"保存策略状态失败: {e}", exc_info=True)
        try:
            # 如果提交失败，尝试回滚
            if hasattr(db, 'is_active') and db.is_active:
                db.rollback()
        except Exception as rollback_error:
            logger.debug(f"回滚失败: {rollback_error}")


def _reset_state(user_strategy, db):
    """重置策略状态"""
    state = _get_strategy_state(user_strategy, db)
    for side in state.keys():
        state[side]['wins'] = 0
        state[side]['last_trend'] = None
        state[side]['replenish_pool'] = []
    _save_strategy_state(user_strategy, db)


def _record_win(side: str, position_size: float, user_strategy, db):
    """记录方向盈利，用于生成补仓机会

    策略逻辑：
    1. 记录当前方向的盈利次数
    2. 每4次盈利为对手方向生成1次补仓额度
    3. 当某方向盈利平仓时，清零对手方向的盈利计数（趋势反转）
    """
    logger.info(f"[_record_win 调用] side={side}, position_size={position_size}, "
                f"user_strategy={user_strategy.id if user_strategy else None}, db={db is not None}")

    if not user_strategy or not db:
        logger.warning(f"[_record_win] 参数无效: user_strategy={user_strategy}, db={db}")
        return

    try:
        # 检查 user_strategy 是否仍然有效
        _ = user_strategy.id
    except Exception as e:
        logger.warning(f"user_strategy 已过期，跳过记录盈利: {e}")
        return

    try:
        # 关键修复：确保直接操作 user_strategy.config 中的数据，而不是副本
        # 先确保 config 和 replenish_state 已初始化
        if not user_strategy.config:
            user_strategy.config = {}
        if 'replenish_state' not in user_strategy.config:
            user_strategy.config['replenish_state'] = {
                'long': {'wins': 0, 'last_trend': None, 'replenish_pool': []},
                'short': {'wins': 0, 'last_trend': None, 'replenish_pool': []}
            }

        # 直接引用 config 中的 replenish_state，确保修改会反映到 config
        state = user_strategy.config['replenish_state']
        opposite = 'short' if side == 'long' else 'long'

        # 趋势反转处理：当某方向盈利平仓时，清零对手方向的盈利计数
        # 防止旧数据影响新趋势的判断
        opposite_wins_before = state[opposite].get('wins', 0)
        if opposite_wins_before > 0:
            logger.info(f"[趋势反转] {side}方向盈利平仓，清零{opposite}方向的盈利计数 "
                       f"(从 {opposite_wins_before} 次清零)")
            state[opposite]['wins'] = 0

        # 记录当前方向的盈利次数
        state[side]['wins'] = state[side].get('wins', 0) + 1
        wins_count = state[side]['wins']
        logger.info(f"[盈利记录] 方向: {side}, 盈利次数: {wins_count}, 保证金: {position_size}")

        # 每4次盈利为相反方向生成补仓额度
        # 注意：先生成补仓额度，再保存状态（一次性保存所有修改）
        if wins_count % 4 == 0 and position_size:
            replenish_amount = max(position_size * 0.5, 0)
            if replenish_amount > 0:
                if 'replenish_pool' not in state[opposite]:
                    state[opposite]['replenish_pool'] = []
                state[opposite]['replenish_pool'].append(replenish_amount)
                logger.info(f"[补仓额度生成] {side}方向盈利{wins_count}次，"
                          f"为{opposite}方向生成补仓额度: {replenish_amount} USDT, "
                          f"{opposite}方向当前补仓池: {state[opposite]['replenish_pool']}")

        # 统一保存状态（包括盈利计数和补仓额度）
        logger.info(f"[准备保存] config['replenish_state'] = {user_strategy.config['replenish_state']}")
        _save_strategy_state(user_strategy, db)

        # 保存后验证
        if wins_count % 4 == 0:
            try:
                db.refresh(user_strategy)
                saved_pool = user_strategy.config.get('replenish_state', {}).get(opposite, {}).get('replenish_pool', [])
                logger.info(f"[保存后验证] 数据库中的补仓池: {saved_pool}")
            except Exception as e:
                logger.warning(f"保存后验证失败: {e}")
    except Exception as e:
        logger.error(f"记录盈利失败: {e}", exc_info=True)


def _update_trend_state(side: str, roi: float, user_strategy, db):
    """监控趋势状态，用于日志记录（不再重置补仓池）"""
    if roi is None:
        return
    if not user_strategy or not db:
        return

    try:
        # 检查 user_strategy 是否仍然有效
        _ = user_strategy.id
    except Exception:
        logger.debug("user_strategy 已过期，跳过趋势状态更新")
        return

    try:
        # 关键修复：直接操作 user_strategy.config，而不是通过 _get_strategy_state 获取可能的副本
        if not user_strategy.config:
            user_strategy.config = {}
        if 'replenish_state' not in user_strategy.config:
            user_strategy.config['replenish_state'] = {
                'long': {'wins': 0, 'last_trend': None, 'replenish_pool': []},
                'short': {'wins': 0, 'last_trend': None, 'replenish_pool': []}
            }

        state = user_strategy.config['replenish_state']

        if roi > 0:
            trend = 'profit'
        elif roi < 0:
            trend = 'loss'
        else:
            trend = 'flat'
        last = state[side].get('last_trend')

        # 记录趋势变化（仅用于日志，不再重置状态）
        # 补仓额度是通过盈利平仓积累的，不应该因为价格波动而丢失
        if last and trend in ('profit', 'loss') and trend != last:
            logger.info(f"[趋势变化] {side}方向从 {last} 转为 {trend}")

        # 只有趋势真正变化时才保存（减少不必要的保存）
        if trend in ('profit', 'loss') and state[side].get('last_trend') != trend:
            state[side]['last_trend'] = trend
            _save_strategy_state(user_strategy, db)
    except Exception as e:
        logger.debug(f"更新趋势状态失败: {e}")

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
        try:
            if not position:
                return None
            
            # 安全地检查 position 是否仍然有效
            try:
                position_id = position.id
                entry_price = position.entry_price
                if not entry_price or entry_price <= 0 or not current_price:
                    return None
            except Exception as e:
                # Position 对象已被删除或过期
                logger.debug(f"持仓对象已失效，跳过自定义退出检查: {e}")
                return None
            
            # 安全地访问 position.side
            try:
                position_side = position.side
            except Exception as e:
                logger.debug(f"无法访问持仓 {position_id} 的 side 属性: {e}")
                return None
            
            # 获取 user_strategy 和 db（如果未传递）
            if not user_strategy and hasattr(position, 'user_strategy'):
                try:
                    user_strategy = position.user_strategy
                except Exception:
                    user_strategy = None
            
            if not db and user_strategy and hasattr(user_strategy, '_sa_instance_state'):
                # 尝试从 user_strategy 获取数据库会话
                from sqlalchemy.orm import object_session
                try:
                    db = object_session(user_strategy) if user_strategy else None
                except Exception:
                    db = None
            
            # 计算盈亏比例（根据持仓方向）
            if position_side == 'long':
                roi = (current_price - entry_price) / entry_price
            else:
                roi = (entry_price - current_price) / entry_price
            
            # 安全地访问 user_strategy
            if user_strategy and db:
                try:
                    # 检查 user_strategy 是否仍然有效
                    _ = user_strategy.id
                    _update_trend_state(position_side, roi, user_strategy, db)
                except Exception as e:
                    logger.debug(f"无法访问 user_strategy，对象可能已过期: {e}")
                    user_strategy = None
                    db = None
            
            # 安全地访问 position 的其他属性
            try:
                leverage = getattr(position, 'leverage', 1) or 1
            except Exception as e:
                logger.debug(f"无法访问持仓 {position_id} 的 leverage 属性: {e}")
                leverage = 1
            
            if leverage <= 0:
                leverage = 1
            
            # 安全地访问 position.size
            try:
                position_size = abs(position.size or 0)
            except Exception as e:
                logger.debug(f"无法访问持仓 {position_id} 的 size 属性: {e}")
                return None
            
            margin_used = (entry_price * position_size) / leverage
            
            # 计算基于保证金的盈亏百分比
            # 优先使用已计算的 unrealized_pnl
            try:
                unrealized_pnl = getattr(position, 'unrealized_pnl', None)
            except Exception as e:
                logger.debug(f"无法访问持仓 {position_id} 的 unrealized_pnl 属性: {e}")
                unrealized_pnl = None
            
            if unrealized_pnl is None:
                # 如果 unrealized_pnl 未设置，手动计算
                if position_side == 'long':
                    unrealized_pnl = (current_price - entry_price) * position_size
                else:
                    unrealized_pnl = (entry_price - current_price) * position_size
            
            if margin_used > 0:
                pnl_percentage = (unrealized_pnl / margin_used) * 100
            else:
                # 如果无法计算保证金，使用价格变动计算
                pnl_percentage = roi * leverage * 100
            
            # 注意：亏损时不平仓，通过 adjust_position 进行补仓处理
            
            # 止盈：盈利超过保证金50%时平仓（考虑杠杆）
            # 注意：_record_win 已在 trading_engine 的 _close_position_from_order 中调用
            # 这里不再重复调用，避免盈利次数被重复计数
            if pnl_percentage >= 50:
                return {
                    'price': current_price,
                    'reason': f'take_profit_{pnl_percentage}pct',
                    'reduce_percent': 1.0  # 全部平仓
                }
            
            return None
        except Exception as e:
            # 捕获所有异常，避免影响主循环
            logger.error(f"custom_exit 执行失败: {e}", exc_info=True)
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
        try:
            if not position:
                return {'should_adjust': False, 'amount': 0}
            
            # 安全地访问 position 属性，如果已被删除会抛出异常
            try:
                # 尝试访问 position.id 来检查对象是否仍然有效
                position_id = position.id
                if not position.is_open:
                    return {'should_adjust': False, 'amount': 0}
            except Exception as e:
                # Position 对象已被删除或过期
                logger.debug(f"持仓对象已失效，跳过仓位调整: {e}")
                return {'should_adjust': False, 'amount': 0}
            
            if not position.entry_price or position.entry_price <= 0:
                return {'should_adjust': False, 'amount': 0}
            
            current_price = position.current_price
            if current_price is None or current_price <= 0:
                return {'should_adjust': False, 'amount': 0}
            
            # 安全地访问 position.side
            try:
                position_side = position.side
            except Exception as e:
                # 如果 position.side 访问失败（对象已过期），直接返回
                logger.warning(f"无法访问持仓 {position_id} 的 side 属性，可能已被删除: {e}")
                return {'should_adjust': False, 'amount': 0}
            
            # 获取 user_strategy 和 db（如果未传递）
            if not user_strategy and hasattr(position, 'user_strategy'):
                try:
                    user_strategy = position.user_strategy
                except Exception:
                    user_strategy = None
            
            if not db and user_strategy and hasattr(user_strategy, '_sa_instance_state'):
                # 尝试从 user_strategy 获取数据库会话
                from sqlalchemy.orm import object_session
                db = object_session(user_strategy) if user_strategy else None
            
            if position_side == 'long':
                roi = (current_price - position.entry_price) / position.entry_price
            else:
                roi = (position.entry_price - current_price) / position.entry_price
            
            # 安全地访问 user_strategy 和 db
            if user_strategy and db:
                try:
                    # 检查 user_strategy 是否仍然有效
                    _ = user_strategy.id
                    _update_trend_state(position_side, roi, user_strategy, db)
                except Exception as e:
                    logger.debug(f"无法访问 user_strategy，对象可能已过期: {e}")
                    user_strategy = None
                    db = None
            
            # 仅在亏损且存在补仓额度时执行
            if user_strategy:
                try:
                    # 再次检查 user_strategy 是否仍然有效
                    _ = user_strategy.id

                    # 关键修复：直接操作 user_strategy.config，而不是通过 _get_strategy_state 获取可能的副本
                    if not user_strategy.config:
                        user_strategy.config = {}
                    if 'replenish_state' not in user_strategy.config:
                        user_strategy.config['replenish_state'] = {
                            'long': {'wins': 0, 'last_trend': None, 'replenish_pool': []},
                            'short': {'wins': 0, 'last_trend': None, 'replenish_pool': []}
                        }

                    state = user_strategy.config['replenish_state']

                    # 确保 replenish_pool 存在于 state 中
                    if 'replenish_pool' not in state[position_side]:
                        state[position_side]['replenish_pool'] = []

                    # 直接引用 state 中的 replenish_pool，确保 pop 操作会修改原数据
                    replenish_pool = state[position_side]['replenish_pool']
                    wins = state[position_side].get('wins', 0)

                    # 获取相反方向的盈利次数（用于生成补仓额度）
                    opposite_side = 'short' if position_side == 'long' else 'long'
                    opposite_wins = state[opposite_side].get('wins', 0)

                    # 补仓检查日志（INFO级别，方便调试）
                    # logger.info(f"[补仓检查] 持仓ID: {position_id}, 方向: {position_side}, "
                    #           f"当前价: {current_price}, 入场价: {position.entry_price}, ROI: {roi:.4f}, "
                    #           f"亏损: {roi < 0}, 补仓池: {len(replenish_pool)}个额度, "
                    #           f"{opposite_side}方向盈利次数: {opposite_wins}")

                    if roi < 0 and replenish_pool:
                        amount = replenish_pool.pop(0)
                        amount = max(amount, 0)
                        if amount > 0:
                            logger.info(f"[补仓触发] 持仓ID: {position_id}, 方向: {position_side}, "
                                      f"补仓数量: {amount}, 剩余补仓额度: {len(replenish_pool)}")
                            if db:
                                try:
                                    _save_strategy_state(user_strategy, db)
                                except Exception as e:
                                    logger.warning(f"保存策略状态失败: {e}")
                            return {
                                'should_adjust': True,
                                'amount': amount
                            }
                    elif roi < 0 and not replenish_pool:
                        # 亏损但无补仓额度
                        logger.debug(f"[补仓未触发] 持仓ID: {position_id}, 方向: {position_side}, "
                                     f"亏损但无补仓额度。需要{opposite_side}方向盈利平仓4次才能生成补仓额度")
                except Exception as e:
                    logger.debug(f"无法获取策略状态，user_strategy 可能已过期: {e}")
            
            return {'should_adjust': False, 'amount': 0}
        except Exception as e:
            # 捕获所有异常，避免影响主循环
            logger.error(f"adjust_position 执行失败: {e}", exc_info=True)
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

