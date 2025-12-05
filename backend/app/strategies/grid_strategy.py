"""
网格交易策略 暂未测试

策略特点：
- 设置基准价和网格大小（百分比）
- 价格跌破下轨时监测买入机会，反弹后买入
- 价格突破上轨时监测卖出机会，回落后卖出
- 支持动态调整网格大小
- 每笔交易使用固定比例资金(10%)

参考:GridBNB-USDT 项目
"""
import logging
import numpy as np
from app.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

# 触发阈值：网格大小的 1/5
def FLIP_THRESHOLD(grid_size: float) -> float:
    return grid_size / 100 / 5


def _get_strategy_state(user_strategy, db=None):
    """获取策略状态"""
    if not user_strategy:
        return _default_state()

    if db:
        try:
            db.refresh(user_strategy)
        except Exception:
            pass

    try:
        config = user_strategy.config or {}
    except Exception:
        return _default_state()

    if 'grid_state' not in config:
        config['grid_state'] = _default_state()
        try:
            user_strategy.config = config
        except Exception:
            pass

    return config['grid_state']


def _default_state():
    return {
        'base_price': None,
        'grid_size': 2.0,  # 默认网格大小 2%
        'highest': None,
        'lowest': None,
        'is_monitoring_buy': False,
        'is_monitoring_sell': False,
    }


def _save_strategy_state(user_strategy, db):
    """保存策略状态"""
    if not db or not user_strategy:
        return
    try:
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(user_strategy, 'config')
        db.flush()
        db.commit()
    except Exception as e:
        logger.warning(f"保存网格策略状态失败: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def populate_indicators(dataframe, metadata):
    """填充指标 - 网格策略不需要复杂指标"""
    return dataframe


def populate_entry_trend_long(dataframe, metadata):
    """做多入场信号 - 由 custom_entry 控制"""
    import pandas as pd
    return pd.Series(False, index=dataframe.index)


def populate_entry_trend_short(dataframe, metadata):
    """做空入场信号 - 网格策略不做空"""
    import pandas as pd
    return pd.Series(False, index=dataframe.index)


def populate_exit_trend_long(dataframe, metadata):
    """出场信号 - 由 custom_exit 控制"""
    import pandas as pd
    return pd.Series(False, index=dataframe.index)


def populate_exit_trend_short(dataframe, metadata):
    """出场信号"""
    import pandas as pd
    return pd.Series(False, index=dataframe.index)


class GridStrategy(BaseStrategy):
    """网格交易策略"""

    def _get_upper_band(self, base_price: float, grid_size: float) -> float:
        """计算上轨"""
        return base_price * (1 + grid_size / 100)

    def _get_lower_band(self, base_price: float, grid_size: float) -> float:
        """计算下轨"""
        return base_price * (1 - grid_size / 100)

    def entry_conditions(self, symbol: str, analysis_result: dict, db=None, user_strategy=None) -> bool:
        """
        入场条件检查 - 网格买入逻辑

        当价格跌破下轨并反弹时触发买入
        """
        if not user_strategy or not db:
            return False

        try:
            dataframe = analysis_result.get('dataframe')
            if dataframe is None or dataframe.empty:
                return False

            current_price = float(dataframe['close'].iloc[-1])
            state = _get_strategy_state(user_strategy, db)

            # 初始化基准价
            if state['base_price'] is None:
                state['base_price'] = current_price
                logger.info(f"[网格策略] {symbol} 初始化基准价: {current_price}")
                _save_strategy_state(user_strategy, db)
                return False

            base_price = state['base_price']
            grid_size = state.get('grid_size', 2.0)
            lower_band = self._get_lower_band(base_price, grid_size)
            threshold = FLIP_THRESHOLD(grid_size)

            # 检查是否跌破下轨
            if current_price < lower_band:
                state['is_monitoring_buy'] = True

                # 更新最低价
                if state['lowest'] is None or current_price < state['lowest']:
                    state['lowest'] = current_price
                    logger.info(f"[网格策略] {symbol} 买入监测 | 当前价: {current_price:.4f} | "
                               f"下轨: {lower_band:.4f} | 最低价: {state['lowest']:.4f}")

                # 检查是否反弹触发买入
                if state['lowest'] and current_price >= state['lowest'] * (1 + threshold):
                    rebound_pct = (current_price / state['lowest'] - 1) * 100
                    logger.info(f"[网格策略] {symbol} 触发买入 | 反弹: {rebound_pct:.2f}%")

                    # 重置监测状态
                    state['is_monitoring_buy'] = False
                    state['lowest'] = None
                    # 买入后更新基准价为当前价
                    state['base_price'] = current_price
                    _save_strategy_state(user_strategy, db)
                    return True

                _save_strategy_state(user_strategy, db)
            else:
                # 价格回升，重置买入监测
                if state['is_monitoring_buy']:
                    logger.info(f"[网格策略] {symbol} 价格回升至 {current_price:.4f}，重置买入监测")
                    state['is_monitoring_buy'] = False
                    state['lowest'] = None
                    _save_strategy_state(user_strategy, db)

            return False

        except Exception as e:
            logger.error(f"[网格策略] 入场条件检查失败: {e}")
            return False

    def custom_exit(self, position, current_price, db=None, user_strategy=None):
        """
        自定义退出逻辑 - 网格卖出

        当价格突破上轨并回落时触发卖出
        """
        if not position or not current_price:
            return None

        try:
            position_id = position.id
            entry_price = position.entry_price
            if not entry_price or entry_price <= 0:
                return None

            # 获取策略状态
            if not user_strategy:
                if hasattr(position, 'user_strategy'):
                    user_strategy = position.user_strategy

            if not db and user_strategy:
                from sqlalchemy.orm import object_session
                db = object_session(user_strategy)

            if not user_strategy or not db:
                return None

            state = _get_strategy_state(user_strategy, db)
            base_price = state.get('base_price') or entry_price
            grid_size = state.get('grid_size', 2.0)
            upper_band = self._get_upper_band(base_price, grid_size)
            threshold = FLIP_THRESHOLD(grid_size)

            # 检查是否突破上轨
            if current_price > upper_band:
                state['is_monitoring_sell'] = True

                # 更新最高价
                if state['highest'] is None or current_price > state['highest']:
                    state['highest'] = current_price
                    logger.info(f"[网格策略] 持仓{position_id} 卖出监测 | 当前价: {current_price:.4f} | "
                               f"上轨: {upper_band:.4f} | 最高价: {state['highest']:.4f}")

                # 检查是否回落触发卖出
                if state['highest'] and current_price <= state['highest'] * (1 - threshold):
                    drop_pct = (1 - current_price / state['highest']) * 100
                    logger.info(f"[网格策略] 持仓{position_id} 触发卖出 | 回落: {drop_pct:.2f}%")

                    # 重置监测状态
                    state['is_monitoring_sell'] = False
                    state['highest'] = None
                    # 卖出后更新基准价
                    state['base_price'] = current_price
                    _save_strategy_state(user_strategy, db)

                    return {
                        'price': current_price,
                        'reason': 'grid_sell',
                        'reduce_percent': 1.0
                    }

                _save_strategy_state(user_strategy, db)
            else:
                # 价格回落，重置卖出监测
                if state['is_monitoring_sell']:
                    logger.info(f"[网格策略] 持仓{position_id} 价格回落至 {current_price:.4f}，重置卖出监测")
                    state['is_monitoring_sell'] = False
                    state['highest'] = None
                    _save_strategy_state(user_strategy, db)

            return None

        except Exception as e:
            logger.error(f"[网格策略] 退出检查失败: {e}")
            return None

    def adjust_position(self, position, db=None, user_strategy=None):
        """网格策略不使用补仓"""
        return {'should_adjust': False, 'amount': 0}


# 创建策略实例
strategy_instance = GridStrategy()
