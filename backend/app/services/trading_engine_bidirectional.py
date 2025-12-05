"""
双向交易执行引擎 - 支持双向持仓、双向补仓、双向平仓

功能特点：
- 支持同时持有多头和空头仓位
- 支持对多头和空头分别补仓
- 支持对多头和空头分别平仓
- 正确的盈亏计算（根据持仓方向）
- 正确的止损止盈判断（根据持仓方向）
- 支持策略返回long/short信号
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import Position, Order, UserStrategy, PnLRecord
from app.models.trade import OrderStatus, OrderSide, OrderType
from app.services.exchange_service import ExchangeService
from app.services.strategy_engine import StrategyEngine
from app.services.base_trading_engine import BaseTradingEngine
from app.services.ohlcv_cache import fetch_ohlcv_batch_sync
from app.core.config import settings
from app.utils.timeframe import parse_timeframe, get_candle_start_timestamp
from app.utils.pnl import calculate_unrealized_pnl
from app.utils.websocket_push import push_position_update_sync
import pandas as pd

logger = logging.getLogger(__name__)


class BidirectionalTradingEngine(BaseTradingEngine):
    """双向交易执行引擎 - 支持双向持仓、双向补仓、双向平仓"""

    def __init__(self, db: Session, user_strategy: UserStrategy,
                 exchange_service: ExchangeService, strategy_engine: StrategyEngine):
        """
        初始化双向交易引擎

        Args:
            db: 数据库会话
            user_strategy: 用户策略配置
            exchange_service: 交易所服务
            strategy_engine: 策略引擎
        """
        super().__init__(db, user_strategy, exchange_service, strategy_engine)

    # 注意：_get_candle_start_timestamp, _get_last_close_candle_timestamp,
    # _set_last_close_candle_timestamp 方法已移到基类 BaseTradingEngine
    # 基类方法支持 side 参数，可直接用于双向交易

    def get_open_positions(self, symbol: Optional[str] = None, side: Optional[str] = None) -> List[Position]:
        """
        获取未平仓交易（支持按交易对和方向筛选）
        
        Args:
            symbol: 交易对（可选）
            side: 方向 'long' 或 'short'（可选）
        """
        # 确保查询时能看到未提交的更改
        self.db.flush()
        
        query = self.db.query(Position).filter(
            Position.user_id == self.user_strategy.user_id,
            Position.user_strategy_id == self.user_strategy.id,
            Position.is_open == True
        )
        
        if symbol:
            query = query.filter(Position.symbol == symbol)
        
        if side:
            query = query.filter(Position.side == side)
        
        positions = query.all()
        logger.debug(f"查询持仓: symbol={symbol}, side={side}, 找到 {len(positions)} 个持仓")
        return positions

    def analyze_strategy(self, symbol: str, dataframe: pd.DataFrame) -> Dict[str, Any]:
        """
        分析策略信号（支持long/short信号）
        
        Returns:
            {
                'entry_signal': bool,  # 是否有入场信号
                'entry_side': 'long' | 'short' | None,  # 入场方向
                'exit_signal': bool,  # 是否有出场信号
                'exit_side': 'long' | 'short' | None,  # 出场方向（如果exit_signal为True）
                'dataframe': DataFrame
            }
        """
        main_timeframe = self.user_strategy.timeframe if self.user_strategy.timeframe else '1h'
        
        metadata = {
            'pair': symbol,
            'timeframe': main_timeframe,
            'main_dataframe': dataframe,
        }
        
        # 获取多时间框架数据（如果启用）
        multi_timeframe_config = self.user_strategy.config.get('multi_timeframe', {})
        if multi_timeframe_config.get('enabled', False):
            long_timeframe = multi_timeframe_config.get('long_timeframe', '4h')
            long_dataframe = self.fetch_ohlcv_data(symbol, long_timeframe, limit=100)
            if long_dataframe is not None and not long_dataframe.empty:
                metadata['long_timeframe'] = long_timeframe
                metadata['long_dataframe'] = long_dataframe
            
            short_timeframe = multi_timeframe_config.get('short_timeframe', '3m')
            short_dataframe = self.fetch_ohlcv_data(symbol, short_timeframe, limit=100)
            if short_dataframe is not None and not short_dataframe.empty:
                metadata['short_timeframe'] = short_timeframe
                metadata['short_dataframe'] = short_dataframe
        
        # 填充指标
        dataframe = self.strategy_engine.populate_indicators(
            self.strategy_module, dataframe, metadata
        )
        
        # 检查入场信号（支持long/short）
        entry_signal = self.strategy_engine.check_entry_signal(
            self.strategy_module, dataframe, metadata
        )
        
        # 检查出场信号（支持long/short）
        exit_signal = self.strategy_engine.check_exit_signal(
            self.strategy_module, dataframe, metadata
        )
        
        # 尝试获取入场方向（如果策略支持）
        entry_side = None
        entry_sides = []
        entry_long_func = self.strategy_engine.get_strategy_function(
            self.strategy_module, 'populate_entry_trend_long'
        )
        entry_short_func = self.strategy_engine.get_strategy_function(
            self.strategy_module, 'populate_entry_trend_short'
        )
        
        if entry_long_func and entry_short_func:
            # 策略分别提供了long和short信号
            long_signal = self.strategy_engine.check_entry_signal(
                self.strategy_module, dataframe, metadata, function_name='populate_entry_trend_long'
            )
            short_signal = self.strategy_engine.check_entry_signal(
                self.strategy_module, dataframe, metadata, function_name='populate_entry_trend_short'
            )
            
            if long_signal:
                entry_sides.append('long')
            if short_signal:
                entry_sides.append('short')
            
            if entry_sides:
                entry_signal = True
                entry_side = entry_sides[0]
        elif entry_signal:
            # 只有通用入场信号，默认使用long（或从metadata中获取）
            entry_side = metadata.get('entry_side', 'long')
        
        # 尝试获取出场方向
        exit_side = None
        exit_long_func = self.strategy_engine.get_strategy_function(
            self.strategy_module, 'populate_exit_trend_long'
        )
        exit_short_func = self.strategy_engine.get_strategy_function(
            self.strategy_module, 'populate_exit_trend_short'
        )
        
        if exit_long_func and exit_short_func:
            long_exit = self.strategy_engine.check_exit_signal(
                self.strategy_module, dataframe, metadata, function_name='populate_exit_trend_long'
            )
            short_exit = self.strategy_engine.check_exit_signal(
                self.strategy_module, dataframe, metadata, function_name='populate_exit_trend_short'
            )
            
            if long_exit:
                exit_side = 'long'
            elif short_exit:
                exit_side = 'short'
        elif exit_signal:
            # 只有通用出场信号，需要根据持仓判断
            exit_side = None  # 将在verify_and_close_positions中根据持仓判断
        
        return {
            'entry_signal': entry_signal,
            'entry_side': entry_side,
            'entry_sides': entry_sides,
            'exit_signal': exit_signal,
            'exit_side': exit_side,
            'dataframe': dataframe
        }
    
    def calculate_unrealized_pnl(self, position: Position, current_price: float) -> float:
        """计算未实现盈亏（根据持仓方向）"""
        return calculate_unrealized_pnl(
            position.entry_price, current_price, position.size, position.side
        )
    
    def check_stop_loss_take_profit(self, position: Position, current_price: float) -> tuple[bool, Optional[str], Optional[float]]:
        """
        检查止损止盈（根据持仓方向）
        
        Args:
            position: 持仓对象
            current_price: 当前价格
        
        Returns:
            (should_close, reason, exit_price)
        """
        if position.side == 'long':
            # 多头：价格下跌触发止损，价格上涨触发止盈
            if position.stop_loss and current_price <= position.stop_loss:
                return True, 'stop_loss', position.stop_loss
            if position.take_profit and current_price >= position.take_profit:
                return True, 'take_profit', position.take_profit
        else:
            # 空头：价格上涨触发止损，价格下跌触发止盈
            if position.stop_loss and current_price >= position.stop_loss:
                return True, 'stop_loss', position.stop_loss
            if position.take_profit and current_price <= position.take_profit:
                return True, 'take_profit', position.take_profit
        
        return False, None, None
    
    def verify_and_close_positions(self, symbol: str, analysis_result: Dict):
        """
        验证现有持仓并视情况平仓（支持双向平仓）
        """
        positions = self.get_open_positions(symbol=symbol)
        
        for position in positions:
            try:
                # 获取当前价格（使用缓存避免重复 API 调用）
                current_price = self._get_cached_price(symbol)
                if not current_price:
                    logger.warning(f"无法获取 {symbol} 价格，跳过持仓检查")
                    continue
                position.current_price = current_price

                # 计算未实现盈亏（根据持仓方向）
                position.unrealized_pnl = self.calculate_unrealized_pnl(position, current_price)
                
                should_close = False
                exit_price = None
                exit_reason = None
                close_amount = None
                
                # 检查止损止盈（根据持仓方向）
                stop_tp_result = self.check_stop_loss_take_profit(position, current_price)
                if stop_tp_result[0]:
                    should_close = True
                    exit_price = stop_tp_result[2]
                    exit_reason = stop_tp_result[1]
                    logger.info(f"触发{exit_reason}: {symbol}, 方向: {position.side}")
                
                # 检查ROI止损（基于保证金亏损百分比，考虑杠杆）
                # 注意：如果策略通过 custom_exit 处理退出逻辑，则禁用引擎的 ROI 止损
                # 双向策略通常通过 custom_exit 和 adjust_position 来处理亏损，不平仓
                # 如果启用了双向交易，默认禁用引擎的 ROI 止损
                is_bidirectional = self.user_strategy.config.get('bidirectional_trading', False)
                disable_engine_stop_loss = self.user_strategy.config.get('disable_engine_stop_loss', is_bidirectional)
                
                if not disable_engine_stop_loss:
                    roi_threshold = self.user_strategy.config.get('stop_loss_roi', settings.DEFAULT_ROI_THRESHOLD)  # 基于保证金
                    if position.entry_price > 0:
                        # 计算保证金（考虑杠杆）
                        leverage = position.leverage or 1
                        if leverage <= 0:
                            leverage = 1
                        margin_used = (position.entry_price * abs(position.size or 0)) / leverage
                        
                        # 基于保证金计算盈亏百分比（已考虑杠杆）
                        if margin_used > 0 and position.unrealized_pnl is not None:
                            pnl_percentage = (position.unrealized_pnl / margin_used) * 100
                            
                            # ROI止损：当保证金亏损百分比达到阈值时平仓
                            if pnl_percentage <= roi_threshold * 100:
                                should_close = True
                                exit_price = current_price
                                exit_reason = "roi_stop_loss"
                                logger.info(f"触发ROI止损: {symbol}, 方向: {position.side}, 保证金亏损: {pnl_percentage:.2f}%, 阈值: {roi_threshold * 100}%")
                        else:
                            # 如果无法计算保证金，回退到基于价格变动的ROI检查
                            if position.side == 'long':
                                current_roi = (current_price - position.entry_price) / position.entry_price
                            else:
                                current_roi = (position.entry_price - current_price) / position.entry_price
                            
                            # 将价格变动ROI转换为杠杆后的盈亏百分比进行比较
                            leverage = position.leverage or 1
                            if leverage <= 0:
                                leverage = 1
                            pnl_percentage = current_roi * leverage * 100
                            
                            if pnl_percentage <= roi_threshold * 100:
                                should_close = True
                                exit_price = current_price
                                exit_reason = "roi_stop_loss"
                                logger.info(f"触发ROI止损（回退模式）: {symbol}, 方向: {position.side}, 盈亏百分比: {pnl_percentage:.2f}%, 阈值: {roi_threshold * 100}%")
                else:
                    logger.debug(f"策略已禁用引擎ROI止损，通过 custom_exit 处理退出逻辑: {symbol}, 方向: {position.side}")
                
                # 检查出场信号（根据持仓方向）
                exit_side = analysis_result.get('exit_side')
                if analysis_result.get('exit_signal', False):
                    # 如果指定了出场方向，只平对应方向的持仓
                    if exit_side is None or exit_side == position.side:
                        should_close = True
                        exit_price = current_price
                        exit_reason = "exit_signal"
                        logger.info(f"触发出场信号: {symbol}, 方向: {position.side}")
                
                # 检查自定义退出
                custom_exit = self.call_strategy_callback('custom_exit', position, current_price, self.db, self.user_strategy)
                if custom_exit:
                    should_close = True
                    exit_price = custom_exit.get('price', current_price)
                    exit_reason = custom_exit.get('reason', 'custom_exit')
                    
                    if 'close_amount' in custom_exit:
                        close_amount = custom_exit.get('close_amount')
                    elif 'reduce_percent' in custom_exit:
                        reduce_percent = custom_exit.get('reduce_percent', 1.0)
                        if reduce_percent < 1.0:
                            close_amount = position.size * reduce_percent
                    
                    logger.info(f"触发自定义退出: {symbol}, 方向: {position.side}, 原因: {exit_reason}")
                
                # 下达平仓订单（根据持仓方向）
                if should_close:
                    self._create_close_order(position, exit_price or current_price, close_amount)
                
                self.db.commit()
            except Exception as e:
                logger.error(f"验证持仓 {position.id} 失败: {e}")
                continue
    
    def _create_close_order(self, position: Position, price: float, amount: Optional[float] = None):
        """
        创建平仓订单（根据持仓方向）
        
        Args:
            position: 持仓对象
            price: 平仓价格
            amount: 平仓数量（如果为None，则平仓全部）
        """
        try:
            close_amount = amount if amount is not None else position.size
            close_amount = min(close_amount, position.size)
            
            if close_amount <= 0:
                logger.warning(f"平仓数量无效: {close_amount}, 跳过平仓")
                return
            
            order_type = OrderType.MARKET if price == position.current_price else OrderType.LIMIT
            
            # 根据持仓方向确定平仓订单方向
            # 多头平仓：卖出（SELL）
            # 空头平仓：买入（BUY）
            if position.side == 'long':
                close_side = OrderSide.SELL
            else:
                close_side = OrderSide.BUY
            
            if self.user_strategy.is_simulated:
                is_partial = close_amount < position.size
                logger.info(f"[模拟模式] 创建{'部分' if is_partial else ''}平仓订单: {position.symbol}, "
                           f"方向: {position.side}, 数量: {close_amount}/{position.size}, 价格: {price}")
                
                # 计算成交金额
                cost = price * close_amount
                
                order = Order(
                    user_id=position.user_id,
                    position_id=position.id,
                    exchange_order_id=f"SIM_{datetime.now().timestamp()}",
                    symbol=position.symbol,
                    side=close_side,
                    type=order_type,
                    amount=close_amount,
                    price=price if order_type == OrderType.LIMIT else None,
                    filled=close_amount,
                    cost=cost,
                    status=OrderStatus.FILLED,
                    filled_at=datetime.now()
                )
                self.db.add(order)
                self.db.commit()
                logger.info(f"[模拟模式] {'部分' if is_partial else ''}平仓订单已创建: {order.id}, 成交价: {price}, 成交金额: {cost}")
                
                # 立即处理订单成交
                self.order_filled(order, {
                    'id': order.exchange_order_id,
                    'symbol': position.symbol,
                    'filled': close_amount,
                    'price': price,
                    'cost': cost,
                    'status': 'closed'
                })
                return
            
            # 实际下单
            exchange_order = self.exchange_service.create_order(
                symbol=position.symbol,
                side=close_side.value,
                order_type=order_type.value,
                amount=close_amount,
                price=price if order_type == OrderType.LIMIT else None
            )
            
            order = Order(
                user_id=position.user_id,
                position_id=position.id,
                exchange_order_id=exchange_order.get('id'),
                symbol=position.symbol,
                side=close_side,
                type=order_type,
                amount=close_amount,
                price=price if order_type == OrderType.LIMIT else None,
                status=OrderStatus.PENDING
            )
            self.db.add(order)
            self.db.commit()
            is_partial = close_amount < position.size
            logger.info(f"创建{'部分' if is_partial else ''}平仓订单: {order.id}, "
                       f"方向: {position.side}, 数量: {close_amount}/{position.size}")
        except Exception as e:
            logger.error(f"创建平仓订单失败: {e}")
            self.db.rollback()
    
    def _close_position_from_order(self, order: Order):
        """从订单关闭持仓（支持双向）"""
        try:
            position = self.db.query(Position).filter(Position.id == order.position_id).first()
            if not position:
                return
            
            # 计算已实现盈亏（根据持仓方向）
            exit_price = order.price or (order.cost / order.filled if order.filled > 0 else 0)
            if position.side == 'long':
                realized_pnl = (exit_price - position.entry_price) * order.filled
            else:
                realized_pnl = (position.entry_price - exit_price) * order.filled
            
            # 更新持仓
            position.size -= order.filled
            position_was_closed = False
            if position.size <= 0:
                position.is_open = False
                position.closed_at = datetime.now()
                position_was_closed = True
                
                timeframe = self.user_strategy.timeframe if self.user_strategy.timeframe else '1h'
                close_candle_timestamp = self._get_candle_start_timestamp(datetime.now(), timeframe)
                self._set_last_close_candle_timestamp(position.symbol, close_candle_timestamp, position.side)
                logger.info(f"记录平仓K线周期: {position.symbol}, 方向: {position.side}, 周期: {close_candle_timestamp}")
            
            # 创建盈亏记录
            effective_leverage = position.leverage or 1
            if effective_leverage <= 0:
                effective_leverage = 1
            
            pnl_record = PnLRecord(
                user_id=order.user_id,
                user_strategy_id=self.user_strategy.id,
                position_id=position.id,
                symbol=order.symbol,
                entry_price=position.entry_price,
                exit_price=exit_price,
                size=order.filled,
                realized_pnl=realized_pnl,
                fee=order.fee,
                pnl_percentage=(
                    (realized_pnl / (position.entry_price * order.filled)) * effective_leverage * 100
                    if position.entry_price > 0 else 0
                )
            )
            self.db.add(pnl_record)
            self.db.commit()
            logger.info(f"关闭持仓: {position.id}, 方向: {position.side}, 盈亏: {realized_pnl}")

            # 如果是盈利平仓，记录盈利次数（用于生成补仓额度）
            if realized_pnl > 0:
                try:
                    from app.strategies.bidirectional_example_strategy import _record_win
                    # 计算该笔平仓对应的保证金（用于生成补仓额度）
                    # 补仓额度 = 盈利持仓保证金的一半
                    position_size = abs(order.filled or 0)
                    leverage = position.leverage or 1
                    if leverage <= 0:
                        leverage = 1
                    # 保证金 = 入场价 × 数量 / 杠杆
                    margin_amount = (position.entry_price * position_size) / leverage if position.entry_price else 0

                    if margin_amount > 0:
                        logger.info(f"[盈利平仓] 记录盈利: 持仓ID={position.id}, 方向={position.side}, "
                                   f"数量={position_size}, 保证金={margin_amount:.4f}, 盈亏={realized_pnl}")
                        _record_win(position.side, margin_amount, self.user_strategy, self.db)
                except ImportError as e:
                    # 如果不是双向交易策略，跳过
                    logger.debug(f"导入 _record_win 失败: {e}")
                except Exception as e:
                    logger.warning(f"记录盈利失败: {e}", exc_info=True)
            else:
                logger.info(f"[亏损平仓] 持仓ID={position.id}, 方向={position.side}, 盈亏={realized_pnl}, 不记录盈利")
            
            # 如果持仓已完全关闭，推送 WebSocket 更新通知前端
            if position_was_closed:
                push_position_update_sync(position, exit_price, is_closed=True)
        except Exception as e:
            logger.error(f"关闭持仓失败: {e}")
            self.db.rollback()

    def adjust_position_size(self, position: Position, current_price: float = None):
        """
        仓位调整（支持双向补仓）

        Args:
            position: 持仓对象
            current_price: 当前价格（可选，如果不传则尝试从持仓获取）
        """
        position_adjustment_enabled = self.user_strategy.config.get('position_adjustment', False)
        if not position_adjustment_enabled:
            logger.debug(f"[仓位调整] 持仓ID: {position.id if position else 'N/A'}, "
                        f"仓位调整功能未启用 (position_adjustment={position_adjustment_enabled})")
            return

        # 检查 position 是否仍然存在于数据库中
        try:
            # 尝试刷新 position 对象，如果已被删除会抛出异常
            self.db.refresh(position)
        except Exception as e:
            logger.warning(f"持仓 {position.id if position else 'N/A'} 已不存在于数据库中，跳过仓位调整: {e}")
            return

        # 再次检查 position 是否仍然开放
        if not position.is_open:
            logger.debug(f"持仓 {position.id} 已关闭，跳过仓位调整")
            return

        # 如果传入了当前价格，更新持仓的 current_price
        if current_price and current_price > 0:
            position.current_price = current_price
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()

        try:
            adjustment = self.call_strategy_callback('adjust_position', position, self.db, self.user_strategy)
            logger.debug(f"[仓位调整] 持仓ID: {position.id}, 策略返回: {adjustment}")
        except Exception as e:
            logger.error(f"调用策略回调 adjust_position 失败: {e}", exc_info=True)
            return
        
        if adjustment and adjustment.get('should_adjust', False):
            logger.info(f"[仓位调整] 持仓ID: {position.id}, 开始执行补仓，数量: {adjustment.get('amount', 0)}")
            try:
                # 再次检查 position 是否仍然有效（可能在回调中被删除）
                self.db.refresh(position)
                if not position.is_open:
                    logger.debug(f"持仓 {position.id} 在回调后已关闭，跳过仓位调整")
                    return
                
                amount = adjustment.get('amount', 0)
                if amount > 0:
                    # 根据持仓方向确定补仓订单方向
                    # 多头补仓：买入（BUY）
                    # 空头补仓：卖出（SELL）
                    if position.side == 'long':
                        adjust_side = OrderSide.BUY
                    else:
                        adjust_side = OrderSide.SELL
                    
                    if self.user_strategy.is_simulated:
                        # 获取当前价格（用于模拟成交）
                        fill_price = current_price or position.current_price or position.entry_price
                        if not fill_price or fill_price <= 0:
                            logger.warning(f"[模拟模式] 仓位调整失败: 无法获取有效价格，持仓ID: {position.id}")
                            return

                        # amount 是保证金（USDT），需要转换为币的数量
                        # 币数量 = 保证金 × 杠杆 / 当前价格
                        leverage = position.leverage or 1
                        if leverage <= 0:
                            leverage = 1
                        coin_amount = (amount * leverage) / fill_price

                        logger.info(f"[模拟模式] 仓位调整: {position.side}方向追加保证金 {amount} USDT，"
                                  f"杠杆={leverage}x，成交价={fill_price}，转换为币数量={coin_amount:.4f}")

                        # 更新持仓：计算新的平均入场价和总数量
                        old_size = abs(position.size or 0)
                        old_entry_price = position.entry_price or fill_price
                        new_size = old_size + coin_amount

                        # 计算新的平均入场价（加权平均）
                        if new_size > 0:
                            new_entry_price = (old_entry_price * old_size + fill_price * coin_amount) / new_size
                        else:
                            new_entry_price = fill_price

                        logger.info(f"[模拟模式] 补仓计算: 原size={old_size:.4f}, 原入场价={old_entry_price:.6f}, "
                                  f"补仓量={coin_amount:.4f}, 补仓价={fill_price:.6f}, 新size={new_size:.4f}, 新入场价={new_entry_price:.6f}")

                        # 更新持仓数据
                        position.size = new_size
                        position.entry_price = new_entry_price

                        # 创建补仓订单（记录币的数量）
                        order = Order(
                            user_id=position.user_id,
                            position_id=position.id,
                            exchange_order_id=f"SIM_{datetime.now().timestamp()}",
                            symbol=position.symbol,
                            side=adjust_side,
                            type=OrderType.MARKET,
                            amount=coin_amount,  # 币的数量
                            filled=coin_amount,  # 模拟模式立即全部成交
                            price=fill_price,
                            cost=amount,  # 保证金（USDT）
                            status=OrderStatus.FILLED
                        )
                        self.db.add(order)

                        # 提交数据库更改
                        try:
                            self.db.commit()
                            # 刷新 position 对象以确认更改已保存
                            self.db.refresh(position)
                            logger.info(f"[模拟模式] 仓位调整完成: 持仓ID={position.id}, "
                                      f"数据库中size={position.size:.4f}, 数据库中入场价={position.entry_price:.6f}")
                        except Exception as commit_error:
                            logger.error(f"[模拟模式] 提交数据库失败: {commit_error}")
                            self.db.rollback()
                            raise
                    else:
                        exchange_order = self.exchange_service.create_order(
                            symbol=position.symbol,
                            side=adjust_side.value,
                            order_type='market',
                            amount=amount
                        )
                        
                        order = Order(
                            user_id=position.user_id,
                            position_id=position.id,
                            exchange_order_id=exchange_order.get('id'),
                            symbol=position.symbol,
                            side=adjust_side,
                            type=OrderType.MARKET,
                            amount=amount,
                            status=OrderStatus.PENDING
                        )
                        self.db.add(order)
                        self.db.commit()
                        logger.info(f"仓位调整: {position.side}方向追加 {amount}")
            except Exception as e:
                logger.error(f"仓位调整失败: {e}")
                self.db.rollback()
    
    def verify_and_open_positions(self, symbol: str, analysis_result: Dict):
        """
        验证入场信号并开仓（支持双向开仓）
        """
        entry_signal = analysis_result.get('entry_signal', False)
        entry_sides = analysis_result.get('entry_sides') or []
        
        if entry_sides:
            for side in entry_sides:
                self._attempt_open_position(symbol, side, analysis_result)
            return
        
        if not entry_signal:
            return
        
        entry_side = analysis_result.get('entry_side', 'long')
        self._attempt_open_position(symbol, entry_side, analysis_result)

    def _attempt_open_position(self, symbol: str, entry_side: str, analysis_result: Dict):
        # 第一次检查：查询现有持仓
        existing_position = self.get_open_positions(symbol=symbol, side=entry_side)
        if existing_position:
            # 注意：仓位调整已在 run_trading_loop 中统一处理，这里只记录日志
            # 使用 DEBUG 级别，因为这是正常情况（已有持仓时跳过开仓）
            logger.debug(f"检测到已有{entry_side}持仓: {symbol}, 持仓ID: {existing_position[0].id}, 跳过开仓")
            return
        
        timeframe = self.user_strategy.timeframe if self.user_strategy.timeframe else '1h'
        last_close_candle = self._get_last_close_candle_timestamp(symbol, side=entry_side)
        if last_close_candle:
            current_candle = self._get_candle_start_timestamp(datetime.now(), timeframe)
            if current_candle == last_close_candle:
                logger.info(f"跳过开仓: {symbol} {entry_side}方向在当前K线周期内已平仓，等待下一个周期")
                return
        
        entry_conditions = self.call_strategy_callback('entry_conditions', symbol, analysis_result)
        if entry_conditions is False:
            logger.info(f"入场条件检查未通过: {symbol} {entry_side}方向，跳过开仓")
            return
        
        # 确保数据库中的未提交更改可见（防止并发问题）
        self.db.flush()
        
        # 第二次检查：双重检查锁定，防止并发创建重复持仓
        existing_position = self.get_open_positions(symbol=symbol, side=entry_side)
        if existing_position:
            # 注意：仓位调整已在 run_trading_loop 中统一处理，这里只记录警告
            logger.warning(f"双重检查发现已有{entry_side}持仓: {symbol}, 持仓ID: {existing_position[0].id}, 跳过开仓（可能是并发导致）")
            return
        
        desired_leverage = self.user_strategy.config.get('leverage', settings.DEFAULT_LEVERAGE) or settings.DEFAULT_LEVERAGE

        try:
            # 获取保证金（从用户配置中，trade_amount 现在代表保证金）
            try:
                margin_amount = float(self.user_strategy.trade_amount) if self.user_strategy.trade_amount else settings.DEFAULT_MARGIN_AMOUNT
            except (ValueError, TypeError):
                margin_amount = settings.DEFAULT_MARGIN_AMOUNT
                logger.warning(f"无法解析交易数量配置，使用默认值 {settings.DEFAULT_MARGIN_AMOUNT} USDT")
            
            # 计算名义价值：名义价值 = 保证金 × 杠杆
            notional_value = margin_amount * desired_leverage
            
            # 获取当前市场价格（使用缓存避免重复 API 调用）
            current_price = self._get_cached_price(symbol)
            if not current_price:
                # 如果获取不到价格，尝试从OHLCV数据获取
                try:
                    ohlcv = self.exchange_service.fetch_ohlcv(symbol, self.user_strategy.timeframe, limit=1)
                    if ohlcv and len(ohlcv) > 0:
                        current_price = ohlcv[-1][4]
                        self._price_cache[symbol] = current_price
                except Exception as e:
                    logger.warning(f"获取 {symbol} OHLCV 价格失败: {e}")
            
            if current_price <= 0:
                logger.error(f"无法获取 {symbol} 的价格，跳过开仓")
                return
            
            # 将名义价值转换为币种数量
            amount = notional_value / current_price
            
            order_side = OrderSide.BUY if entry_side == 'long' else OrderSide.SELL
            logger.info(f"创建{entry_side}仓订单: {symbol}, 保证金: {margin_amount} USDT, 杠杆: {desired_leverage}x, 名义价值: {notional_value} USDT, 币种数量: {amount}, 价格: {current_price}")
            
            if not self.user_strategy.is_simulated:
                try:
                    self.exchange_service.set_leverage(int(desired_leverage), symbol)
                except Exception as e:
                    logger.warning(f"设置 {symbol} 杠杆为 {desired_leverage}x 失败: {e}")
            
            if self.user_strategy.is_simulated:
                logger.info(f"[模拟模式] 创建{entry_side}仓订单: {symbol}, 保证金: {margin_amount} USDT, 杠杆: {desired_leverage}x, 名义价值: {notional_value} USDT, 币种数量: {amount}, 价格: {current_price}")
                
                # 计算成交金额（名义价值，即实际开仓价值）
                cost = notional_value
                order = Order(
                    user_id=self.user_strategy.user_id,
                    exchange_order_id=f"SIM_{datetime.now().timestamp()}",
                    symbol=symbol,
                    side=order_side,
                    type=OrderType.MARKET,
                    amount=amount,
                    price=current_price,
                    filled=amount,
                    cost=cost,
                    status=OrderStatus.FILLED
                )
                self.db.add(order)
                self.db.commit()
                logger.info(f"[模拟模式] {entry_side}仓订单已创建: {order.id}")
                
                self.order_filled(order, {
                    'id': order.exchange_order_id,
                    'symbol': symbol,
                    'filled': amount,
                    'price': current_price,
                    'cost': cost,
                    'status': 'closed'
                })
                return
            
            exchange_order = self.exchange_service.create_order(
                symbol=symbol,
                side=order_side.value,
                order_type='market',
                amount=amount
            )
            
            order = Order(
                user_id=self.user_strategy.user_id,
                exchange_order_id=exchange_order.get('id'),
                symbol=symbol,
                side=order_side,
                type=OrderType.MARKET,
                amount=amount,
                status=OrderStatus.PENDING
            )
            self.db.add(order)
            self.db.commit()
            logger.info(f"创建{entry_side}仓订单: {order.id}, 交易对: {symbol}")
        except Exception as e:
            logger.error(f"创建{entry_side}仓订单失败: {e}")
            self.db.rollback()
    
    def order_filled(self, order: Order, exchange_order: Dict):
        """订单成交回调函数（支持双向）"""
        logger.info(f"订单 {order.id} 已成交")
        
        self.call_strategy_callback('order_filled', order, exchange_order)
        
        # 如果是开仓订单，创建持仓记录（支持long和short）
        if order.position_id is None:
            if order.side == OrderSide.BUY:
                # 买入订单：开多仓
                self._create_position_from_order(order, 'long')
            elif order.side == OrderSide.SELL:
                # 卖出订单：开空仓
                self._create_position_from_order(order, 'short')
        else:
            # 如果是平仓订单，更新持仓
            self._close_position_from_order(order)
    
    def _create_position_from_order(self, order: Order, side: str):
        """从订单创建持仓（支持long和short）"""
        try:
            position_size = order.filled if order.filled and order.filled > 0 else order.amount
            
            if order.price and order.price > 0:
                entry_price = order.price
            elif order.cost and order.cost > 0 and position_size > 0:
                entry_price = order.cost / position_size
            else:
                try:
                    ticker = self.exchange_service.exchange.fetch_ticker(order.symbol)
                    entry_price = ticker.get('last', 0)
                    if entry_price == 0:
                        logger.warning(f"无法获取 {order.symbol} 的价格，使用默认值")
                        entry_price = 0
                except Exception as e:
                    logger.warning(f"获取 {order.symbol} 价格失败: {e}")
                    entry_price = 0
            
            if position_size <= 0:
                logger.warning(f"订单 {order.id} 的持仓数量为 0，跳过创建持仓")
                return
            
            if entry_price <= 0:
                logger.warning(f"订单 {order.id} 的开仓价格为 0，可能无法正确计算盈亏")
            
            # 获取杠杆（默认 50x，可由策略配置覆盖）
            leverage = self.user_strategy.config.get('leverage', 50) or 50
            try:
                positions = self.exchange_service.fetch_positions(order.symbol)
                if positions:
                    for pos in positions:
                        if pos.get('symbol') == order.symbol:
                            leverage = pos.get('leverage', leverage) or leverage
                            break
            except Exception as e:
                logger.debug(f"获取 {order.symbol} 杠杆信息失败: {e}，使用默认值 {leverage}x")
            
            # 再次检查是否已有持仓（防止并发创建）
            existing_position = self.get_open_positions(symbol=order.symbol, side=side)
            if existing_position:
                logger.warning(f"在创建持仓前检测到已有{side}持仓: {order.symbol}, 持仓ID: {existing_position[0].id}, 跳过创建新持仓")
                order.position_id = existing_position[0].id
                self.db.commit()
                return
            
            position = Position(
                user_id=order.user_id,
                user_strategy_id=self.user_strategy.id,
                symbol=order.symbol,
                side=side,  # 'long' 或 'short'
                size=position_size,
                entry_price=entry_price,
                current_price=entry_price,
                leverage=leverage,
                is_open=True
            )
            self.db.add(position)
            # 先flush以获取position.id（对于自增ID）
            self.db.flush()
            order.position_id = position.id
            self.db.commit()
            logger.info(f"创建{side}仓: {position.id}, 交易对: {order.symbol}, 数量: {position_size}, "
                       f"开仓价: {entry_price}, 杠杆: {leverage}x")
        except Exception as e:
            logger.error(f"创建持仓失败: {e}", exc_info=True)
            self.db.rollback()

    def update_positions_prices(self):
        """更新所有持仓的当前价格和盈亏"""
        try:
            positions = self.get_open_positions()
            for position in positions:
                try:
                    # 获取当前价格（使用缓存避免重复 API 调用）
                    current_price = self._get_cached_price(position.symbol)
                    if current_price and current_price > 0:
                        position.current_price = current_price
                        position.unrealized_pnl = self.calculate_unrealized_pnl(position, current_price)
                        self.db.commit()
                except Exception as e:
                    logger.warning(f"更新持仓 {position.id} 价格失败: {e}")
                    continue
        except Exception as e:
            logger.error(f"更新持仓价格失败: {e}")

    def run_trading_loop(self):
        """执行交易循环（支持双向交易）"""
        # 清空价格缓存，确保每次循环获取最新价格
        self._clear_price_cache()

        try:
            open_positions = self.get_open_positions()
            # logger.info(f"当前未平仓交易数: {len(open_positions)} (多头: {len([p for p in open_positions if p.side == 'long'])}, "
            #            f"空头: {len([p for p in open_positions if p.side == 'short'])})")
            
            self.update_positions_prices()
            
            tradable_symbols = self.get_tradable_symbols()
            # logger.info(f"可交易对数量: {len(tradable_symbols)}")

            self.call_strategy_callback('before_loop', tradable_symbols)

            # 批量并行获取所有交易对的 OHLCV 数据
            timeframe = self.get_timeframe()
            ohlcv_data = fetch_ohlcv_batch_sync(
                self.exchange_service,
                tradable_symbols,
                timeframe,
                limit=settings.DEFAULT_OHLCV_LIMIT,
                max_workers=5
            )

            # 更新订单状态（移到循环外，只需执行一次）
            self.update_order_status()

            # 循环开始前一次性获取所有持仓，按 symbol 分组（优化：减少数据库查询）
            all_positions = self.get_open_positions()
            positions_by_symbol: Dict[str, List[Position]] = {}
            for pos in all_positions:
                if pos.symbol not in positions_by_symbol:
                    positions_by_symbol[pos.symbol] = []
                positions_by_symbol[pos.symbol].append(pos)

            for symbol in tradable_symbols:
                try:
                    # 从批量获取的结果中取数据
                    dataframe = ohlcv_data.get(symbol)
                    if dataframe is None or dataframe.empty:
                        continue

                    analysis_result = self.analyze_strategy(symbol, dataframe)

                    # 获取当前价格（从 K 线数据的最新收盘价）
                    current_price = None
                    if dataframe is not None and not dataframe.empty:
                        current_price = float(dataframe['close'].iloc[-1])

                    self.verify_and_close_positions(symbol, analysis_result)

                    # 从预先获取的持仓映射中获取当前 symbol 的持仓
                    # 注意：verify_and_close_positions 可能已关闭某些持仓，需要过滤
                    current_positions = [
                        pos for pos in positions_by_symbol.get(symbol, [])
                        if pos.is_open
                    ]

                    # 对当前 symbol 的持仓进行仓位调整（传入最新价格）
                    for position in current_positions:
                        try:
                            self.adjust_position_size(position, current_price)
                        except Exception as e:
                            logger.error(f"调整持仓 {position.id if position else 'N/A'} 失败: {e}")
                            continue

                    self.verify_and_open_positions(symbol, analysis_result)

                except Exception as e:
                    logger.error(f"处理交易对 {symbol} 失败: {e}")
                    continue
            
            self.call_strategy_callback('after_loop', tradable_symbols)
            
        except Exception as e:
            # 详细记录双向交易循环异常信息
            exception_type = type(e).__name__
            exception_message = str(e)
            user_strategy_id = self.user_strategy.id if self.user_strategy else '未知'
            logger.error(
                f"双向交易循环执行异常终止 - "
                f"策略ID: {user_strategy_id}, "
                f"异常类型: {exception_type}, "
                f"异常消息: {exception_message}",
                exc_info=True
            )
            raise

