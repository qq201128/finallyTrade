"""
交易执行引擎 - 实现系统逻辑循环
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
from app.utils.websocket_push import push_position_update_sync
import pandas as pd

logger = logging.getLogger(__name__)


class TradingEngine(BaseTradingEngine):
    """交易执行引擎"""

    def __init__(self, db: Session, user_strategy: UserStrategy,
                 exchange_service: ExchangeService, strategy_engine: StrategyEngine):
        """
        初始化交易引擎

        Args:
            db: 数据库会话
            user_strategy: 用户策略配置
            exchange_service: 交易所服务
            strategy_engine: 策略引擎
        """
        super().__init__(db, user_strategy, exchange_service, strategy_engine)

    # 注意：_get_candle_start_timestamp, _get_last_close_candle_timestamp,
    # _set_last_close_candle_timestamp 方法已移到基类 BaseTradingEngine

    def get_open_positions(self, symbol: str = None, side: str = None) -> List[Position]:
        """
        步骤1: 从持久化存储中获取未平仓交易

        Args:
            symbol: 交易对（可选，TradingEngine 不使用）
            side: 方向（可选，TradingEngine 不使用）
        """
        positions = self.db.query(Position).filter(
            Position.user_id == self.user_strategy.user_id,
            Position.user_strategy_id == self.user_strategy.id,
            Position.is_open == True
        ).all()
        return positions
    
    def analyze_strategy(self, symbol: str, dataframe: pd.DataFrame) -> Dict[str, bool]:
        """
        步骤5: 按交易对分析策略
        调用入场和出场信号需要指标
        支持多时间框架分析
        """
        main_timeframe = self.user_strategy.timeframe if self.user_strategy.timeframe else '1h'
        
        # 构建metadata，包含主时间框架数据
        metadata = {
            'pair': symbol,
            'timeframe': main_timeframe,
            'main_dataframe': dataframe,  # 主时间框架数据
        }
        
        # 获取多时间框架数据（如果策略需要）
        # 从用户策略配置中读取多时间框架设置
        multi_timeframe_config = self.user_strategy.config.get('multi_timeframe', {})
        if multi_timeframe_config.get('enabled', False):
            # 获取长期时间框架数据（如4小时）
            long_timeframe = multi_timeframe_config.get('long_timeframe', '4h')
            long_dataframe = self.fetch_ohlcv_data(symbol, long_timeframe, limit=100)
            if long_dataframe is not None and not long_dataframe.empty:
                metadata['long_timeframe'] = long_timeframe
                metadata['long_dataframe'] = long_dataframe
            
            # 获取短期时间框架数据（如3分钟）
            short_timeframe = multi_timeframe_config.get('short_timeframe', '3m')
            short_dataframe = self.fetch_ohlcv_data(symbol, short_timeframe, limit=100)
            if short_dataframe is not None and not short_dataframe.empty:
                metadata['short_timeframe'] = short_timeframe
                metadata['short_dataframe'] = short_dataframe
        
        # 填充指标（传递多时间框架数据）
        dataframe = self.strategy_engine.populate_indicators(
            self.strategy_module, dataframe, metadata
        )
        
        # 检查入场信号
        entry_signal = self.strategy_engine.check_entry_signal(
            self.strategy_module, dataframe, metadata
        )
        
        # 检查出场信号
        exit_signal = self.strategy_engine.check_exit_signal(
            self.strategy_module, dataframe, metadata
        )
        
        return {
            'entry_signal': entry_signal,
            'exit_signal': exit_signal,
            'dataframe': dataframe
        }
    
    def order_filled(self, order: Order, exchange_order: Dict):
        """
        订单成交回调函数
        无论订单类型（入场、出场、止损或仓位调整），回调函数都会被调用
        """
        logger.info(f"订单 {order.id} 已成交")
        
        # 调用策略的order_filled回调（如果存在）
        self.call_strategy_callback('order_filled', order, exchange_order)
        
        # 如果是开仓订单，创建持仓记录
        if order.position_id is None and order.side == OrderSide.BUY:
            self._create_position_from_order(order)
        # 如果是平仓订单，更新持仓
        elif order.position_id:
            self._close_position_from_order(order)
    
    def _create_position_from_order(self, order: Order):
        """从订单创建持仓"""
        try:
            # 使用 filled 或 amount 作为持仓数量
            position_size = order.filled if order.filled and order.filled > 0 else order.amount
            
            # 计算开仓价格
            if order.price and order.price > 0:
                entry_price = order.price
            elif order.cost and order.cost > 0 and position_size > 0:
                entry_price = order.cost / position_size
            else:
                # 如果都没有，尝试从交易所获取当前价格
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
            
            # 尝试从交易所获取杠杆信息
            leverage = 1  # 默认杠杆
            try:
                # 尝试从交易所获取持仓信息以获取杠杆
                positions = self.exchange_service.fetch_positions(order.symbol)
                if positions:
                    # 查找匹配的持仓
                    for pos in positions:
                        if pos.get('symbol') == order.symbol:
                            leverage = pos.get('leverage', 1) or 1
                            break
            except Exception as e:
                logger.debug(f"获取 {order.symbol} 杠杆信息失败: {e}，使用默认值 1x")
                # 如果获取失败，尝试从用户策略配置中获取
                leverage = self.user_strategy.config.get('leverage', 1) or 1
            
            position = Position(
                user_id=order.user_id,
                user_strategy_id=self.user_strategy.id,
                symbol=order.symbol,
                side='long',  # 可以根据订单类型判断
                size=position_size,
                entry_price=entry_price,
                current_price=entry_price,  # 初始当前价格等于开仓价格
                leverage=leverage,
                is_open=True
            )
            self.db.add(position)
            order.position_id = position.id
            self.db.commit()
            logger.info(f"创建持仓: {position.id}, 交易对: {order.symbol}, 数量: {position_size}, 开仓价: {entry_price}, 杠杆: {leverage}x")
        except Exception as e:
            logger.error(f"创建持仓失败: {e}", exc_info=True)
            self.db.rollback()
    
    def _close_position_from_order(self, order: Order):
        """从订单关闭持仓"""
        try:
            position = self.db.query(Position).filter(Position.id == order.position_id).first()
            if not position:
                return
            
            # 计算已实现盈亏
            exit_price = order.price or (order.cost / order.filled if order.filled > 0 else 0)
            realized_pnl = (exit_price - position.entry_price) * order.filled
            
            # 更新持仓
            position.size -= order.filled
            position_was_closed = False
            if position.size <= 0:
                position.is_open = False
                position.closed_at = datetime.now()
                position_was_closed = True
                
                # 记录平仓时的K线周期时间戳，用于防止同一周期内立即开仓
                timeframe = self.user_strategy.timeframe if self.user_strategy.timeframe else '1h'
                close_candle_timestamp = self._get_candle_start_timestamp(datetime.now(), timeframe)
                self._set_last_close_candle_timestamp(position.symbol, close_candle_timestamp)
                logger.info(f"记录平仓K线周期: {position.symbol}, 周期: {close_candle_timestamp}")
            
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
            logger.info(f"关闭持仓: {position.id}, 盈亏: {realized_pnl}")
            
            # 如果持仓已完全关闭，推送 WebSocket 更新通知前端
            if position_was_closed:
                push_position_update_sync(position, exit_price, is_closed=True)
        except Exception as e:
            logger.error(f"关闭持仓失败: {e}")
            self.db.rollback()

    def verify_and_close_positions(self, symbol: str, analysis_result: Dict):
        """
        步骤7: 验证现有持仓并视情况下达卖出平仓订单
        7.1 考虑止损ROI和卖出信号和自定义退出
        7.2 可以根据退出价格配置确定卖出价格
        """
        positions = self.db.query(Position).filter(
            Position.user_id == self.user_strategy.user_id,
            Position.user_strategy_id == self.user_strategy.id,
            Position.symbol == symbol,
            Position.is_open == True
        ).all()
        
        for position in positions:
            try:
                # 获取当前价格（使用缓存避免重复 API 调用）
                current_price = self._get_cached_price(symbol)
                if not current_price:
                    logger.warning(f"无法获取 {symbol} 价格，跳过持仓检查")
                    continue
                position.current_price = current_price

                # 计算未实现盈亏
                qty = abs(position.size or 0)
                position.unrealized_pnl = (current_price - position.entry_price) * qty
                
                should_close = False
                exit_price = None
                exit_reason = None
                
                # 检查止损
                if position.stop_loss and current_price <= position.stop_loss:
                    should_close = True
                    exit_price = position.stop_loss
                    exit_reason = "stop_loss"
                    logger.info(f"触发止损: {symbol}")
                
                # 检查止盈
                if position.take_profit and current_price >= position.take_profit:
                    should_close = True
                    exit_price = position.take_profit
                    exit_reason = "take_profit"
                    logger.info(f"触发止盈: {symbol}")
                
                # 检查ROI（从配置中获取）
                roi_threshold = self.user_strategy.config.get('stop_loss_roi', settings.DEFAULT_ROI_THRESHOLD)
                current_roi = (current_price - position.entry_price) / position.entry_price
                if current_roi <= roi_threshold:
                    should_close = True
                    exit_price = current_price  # 市价平仓
                    exit_reason = "roi_stop_loss"
                    logger.info(f"触发ROI止损: {symbol}, ROI: {current_roi}")
                
                # 检查卖出信号
                if analysis_result.get('exit_signal', False):
                    should_close = True
                    exit_price = current_price  # 市价平仓
                    exit_reason = "exit_signal"
                    logger.info(f"触发卖出信号: {symbol}")
                
                # 检查自定义退出（从策略回调）
                custom_exit = self.call_strategy_callback('custom_exit', position, current_price)
                close_amount = None  # 初始化平仓数量
                if custom_exit:
                    should_close = True
                    exit_price = custom_exit.get('price', current_price)
                    exit_reason = custom_exit.get('reason', 'custom_exit')
                    # 支持部分平仓：从custom_exit中获取reduce_percent或close_amount
                    if 'close_amount' in custom_exit:
                        # 直接指定平仓数量
                        close_amount = custom_exit.get('close_amount')
                        logger.info(f"触发自定义部分退出: {symbol}, 原因: {exit_reason}, 平仓数量: {close_amount}/{position.size}")
                    elif 'reduce_percent' in custom_exit:
                        # 指定平仓比例
                        reduce_percent = custom_exit.get('reduce_percent', 1.0)
                        if reduce_percent < 1.0:
                            close_amount = position.size * reduce_percent
                            logger.info(f"触发自定义部分退出: {symbol}, 原因: {exit_reason}, 平仓比例: {reduce_percent*100}%, 数量: {close_amount}")
                        else:
                            logger.info(f"触发自定义退出: {symbol}, 原因: {exit_reason}")
                    else:
                        logger.info(f"触发自定义退出: {symbol}, 原因: {exit_reason}")
                
                # 下达平仓订单
                if should_close:
                    self._create_close_order(position, exit_price or current_price, close_amount)
                
                self.db.commit()
            except Exception as e:
                logger.error(f"验证持仓 {position.id} 失败: {e}")
                continue
    
    def _create_close_order(self, position: Position, price: float, amount: Optional[float] = None):
        """
        创建平仓订单（支持部分平仓）
        
        Args:
            position: 持仓对象
            price: 平仓价格
            amount: 平仓数量（如果为None，则平仓全部）
        """
        try:
            # 如果没有指定数量，则平仓全部
            close_amount = amount if amount is not None else position.size
            # 确保不超过持仓数量
            close_amount = min(close_amount, position.size)
            
            if close_amount <= 0:
                logger.warning(f"平仓数量无效: {close_amount}, 跳过平仓")
                return
            
            order_type = OrderType.MARKET if price == position.current_price else OrderType.LIMIT
            
            # 如果是模拟模式，不实际下单，只记录日志
            if self.user_strategy.is_simulated:
                is_partial = close_amount < position.size
                logger.info(f"[模拟模式] 创建{'部分' if is_partial else ''}平仓订单: {position.symbol}, 数量: {close_amount}/{position.size}, 价格: {price}")
                # 创建模拟订单记录
                order = Order(
                    user_id=position.user_id,
                    position_id=position.id,
                    exchange_order_id=f"SIM_{datetime.now().timestamp()}",
                    symbol=position.symbol,
                    side=OrderSide.SELL,
                    type=order_type,
                    amount=close_amount,
                    price=price if order_type == OrderType.LIMIT else None,
                    status=OrderStatus.FILLED  # 模拟模式下直接标记为已成交
                )
                self.db.add(order)
                self.db.commit()
                logger.info(f"[模拟模式] {'部分' if is_partial else ''}平仓订单已创建: {order.id}")
                return
            
            # 实际下单
            exchange_order = self.exchange_service.create_order(
                symbol=position.symbol,
                side='sell',
                order_type=order_type.value,
                amount=close_amount,
                price=price if order_type == OrderType.LIMIT else None
            )
            
            # 创建订单记录
            order = Order(
                user_id=position.user_id,
                position_id=position.id,
                exchange_order_id=exchange_order.get('id'),
                symbol=position.symbol,
                side=OrderSide.SELL,
                type=order_type,
                amount=close_amount,
                price=price if order_type == OrderType.LIMIT else None,
                status=OrderStatus.PENDING
            )
            self.db.add(order)
            self.db.commit()
            is_partial = close_amount < position.size
            logger.info(f"创建{'部分' if is_partial else ''}平仓订单: {order.id}, 数量: {close_amount}/{position.size}")
        except Exception as e:
            logger.error(f"创建平仓订单失败: {e}")
            self.db.rollback()
    
    def adjust_position_size(self, position: Position):
        """
        步骤8: 如果启用了仓位调整功能
        检查未平仓交易，并在需要时下达追加订单
        """
        if not self.user_strategy.config.get('position_adjustment', False):
            return
        
        # 调用策略的仓位调整回调
        adjustment = self.call_strategy_callback('adjust_position', position)
        if adjustment and adjustment.get('should_adjust', False):
            try:
                amount = adjustment.get('amount', 0)
                if amount > 0:
                    # 如果是模拟模式，不实际下单
                    if self.user_strategy.is_simulated:
                        logger.info(f"[模拟模式] 仓位调整: 追加买入 {amount} {position.symbol}")
                        order = Order(
                            user_id=position.user_id,
                            position_id=position.id,
                            exchange_order_id=f"SIM_{datetime.now().timestamp()}",
                            symbol=position.symbol,
                            side=OrderSide.BUY,
                            type=OrderType.MARKET,
                            amount=amount,
                            status=OrderStatus.FILLED
                        )
                        self.db.add(order)
                        self.db.commit()
                        logger.info(f"[模拟模式] 仓位调整订单已创建: {order.id}")
                    else:
                        # 实际下单
                        exchange_order = self.exchange_service.create_order(
                            symbol=position.symbol,
                            side='buy',
                            order_type='market',
                            amount=amount
                        )
                        
                        order = Order(
                            user_id=position.user_id,
                            position_id=position.id,
                            exchange_order_id=exchange_order.get('id'),
                            symbol=position.symbol,
                            side=OrderSide.BUY,
                            type=OrderType.MARKET,
                            amount=amount,
                            status=OrderStatus.PENDING
                        )
                        self.db.add(order)
                        self.db.commit()
                        logger.info(f"仓位调整: 追加买入 {amount}")
            except Exception as e:
                logger.error(f"仓位调整失败: {e}")
                self.db.rollback()
    
    def verify_and_open_positions(self, symbol: str, analysis_result: Dict):
        """
        步骤9: 验证买入信号，尝试开立新仓位
        下达买入订单前，会调用入场条件函数
        """
        if not analysis_result.get('entry_signal', False):
            return
        
        # 检查是否已有持仓
        existing_position = self.db.query(Position).filter(
            Position.user_id == self.user_strategy.user_id,
            Position.user_strategy_id == self.user_strategy.id,
            Position.symbol == symbol,
            Position.is_open == True
        ).first()
        
        if existing_position:
            # 如果已有持仓，可能进行仓位调整
            self.adjust_position_size(existing_position)
            return
        
        # 检查是否在同一个K线周期内平仓过，如果是则跳过开仓
        timeframe = self.user_strategy.timeframe if self.user_strategy.timeframe else '1h'
        last_close_candle = self._get_last_close_candle_timestamp(symbol)
        if last_close_candle:
            current_candle = self._get_candle_start_timestamp(datetime.now(), timeframe)
            if current_candle == last_close_candle:
                logger.info(f"跳过开仓: {symbol} 在当前K线周期内已平仓，等待下一个周期")
                return
        
        # 调用入场条件函数（如果存在）
        entry_conditions = self.call_strategy_callback('entry_conditions', symbol, analysis_result)
        if entry_conditions is False:
            return
        
        try:
            # 获取保证金（从用户配置中，trade_amount 现在代表保证金）
            try:
                margin_amount = float(self.user_strategy.trade_amount) if self.user_strategy.trade_amount else settings.DEFAULT_MARGIN_AMOUNT
            except (ValueError, TypeError):
                margin_amount = settings.DEFAULT_MARGIN_AMOUNT
                logger.warning(f"无法解析交易数量配置 '{self.user_strategy.trade_amount}'，使用默认值 {settings.DEFAULT_MARGIN_AMOUNT} USDT")

            # 获取杠杆倍数（从配置中获取）
            leverage = self.user_strategy.config.get('leverage', settings.DEFAULT_LEVERAGE) or settings.DEFAULT_LEVERAGE
            if leverage <= 0:
                leverage = 1
            
            # 计算名义价值：名义价值 = 保证金 × 杠杆
            notional_value = margin_amount * leverage
            
            # 获取当前市场价格（使用缓存避免重复 API 调用）
            current_price = self._get_cached_price(symbol)
            if not current_price:
                # 如果获取不到价格，尝试从OHLCV数据获取
                try:
                    ohlcv = self.exchange_service.fetch_ohlcv(symbol, self.user_strategy.timeframe, limit=1)
                    if ohlcv and len(ohlcv) > 0:
                        current_price = ohlcv[-1][4]  # close price
                        self._price_cache[symbol] = current_price
                except Exception as e:
                    logger.warning(f"获取 {symbol} OHLCV 价格失败: {e}")
            
            if current_price <= 0:
                logger.error(f"无法获取 {symbol} 的价格，跳过开仓")
                return
            
            # 将名义价值转换为币种数量
            # 币种数量 = 名义价值 / 当前价格
            amount = notional_value / current_price
            
            logger.info(f"交易配置: 保证金={margin_amount} USDT, 杠杆={leverage}x, 名义价值={notional_value} USDT, 当前价格={current_price}, 计算币种数量={amount}")
            
            # 如果是模拟模式，不实际下单，只记录日志
            if self.user_strategy.is_simulated:
                logger.info(f"[模拟模式] 创建买入订单: {symbol}, 保证金: {margin_amount} USDT, 杠杆: {leverage}x, 名义价值: {notional_value} USDT, 币种数量: {amount}, 价格: {current_price}")
                
                # 计算成交金额（名义价值，即实际开仓价值）
                cost = notional_value  # 使用名义价值
                
                # 创建模拟订单记录
                order = Order(
                    user_id=self.user_strategy.user_id,
                    exchange_order_id=f"SIM_{datetime.now().timestamp()}",
                    symbol=symbol,
                    side=OrderSide.BUY,
                    type=OrderType.MARKET,
                    amount=amount,  # 币种数量
                    price=current_price,
                    filled=amount,  # 币种数量
                    cost=cost,  # USDT数量
                    status=OrderStatus.FILLED  # 模拟模式下直接标记为已成交
                )
                self.db.add(order)
                self.db.commit()
                logger.info(f"[模拟模式] 买入订单已创建: {order.id}, 价格: {current_price}, 币种数量: {amount}, USDT成本: {cost}")
                
                # 模拟订单成交后，创建持仓并调用 order_filled 回调
                self.order_filled(order, {
                    'id': order.exchange_order_id,
                    'symbol': symbol,
                    'filled': amount,  # 币种数量
                    'price': current_price,
                    'cost': cost,  # USDT数量
                    'status': 'closed'
                })
                return
            
            # 实际下单（使用币种数量）
            logger.info(f"创建买入订单: {symbol}, 保证金: {margin_amount} USDT, 杠杆: {leverage}x, 名义价值: {notional_value} USDT, 币种数量: {amount}, 价格: {current_price}")
            exchange_order = self.exchange_service.create_order(
                symbol=symbol,
                side='buy',
                order_type='market',
                amount=amount
            )
            
            # 创建订单记录
            order = Order(
                user_id=self.user_strategy.user_id,
                exchange_order_id=exchange_order.get('id'),
                symbol=symbol,
                side=OrderSide.BUY,
                type=OrderType.MARKET,
                amount=amount,
                status=OrderStatus.PENDING
            )
            self.db.add(order)
            self.db.commit()
            logger.info(f"创建买入订单: {order.id}, 交易对: {symbol}")
        except Exception as e:
            logger.error(f"创建买入订单失败: {e}")
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
                        # 计算未实现盈亏
                        if position.entry_price:
                            qty = abs(position.size or 0)
                            position.unrealized_pnl = (current_price - position.entry_price) * qty
                        self.db.commit()
                except Exception as e:
                    logger.warning(f"更新持仓 {position.id} 价格失败: {e}")
                    continue
        except Exception as e:
            logger.error(f"更新持仓价格失败: {e}")
    
    def run_trading_loop(self):
        """
        执行交易循环
        此循环将不断重复，直到机器人停止
        """
        logger.info(f"开始交易循环: 用户策略 {self.user_strategy.id}")

        # 清空价格缓存，确保每次循环获取最新价格
        self._clear_price_cache()

        try:
            # 步骤1: 获取未平仓交易
            open_positions = self.get_open_positions()
            logger.info(f"当前未平仓交易数: {len(open_positions)}")
            
            # 更新持仓的当前价格和盈亏
            self.update_positions_prices()
            
            # 步骤2: 获取可交易对列表
            tradable_symbols = self.get_tradable_symbols()
            logger.info(f"可交易对数量: {len(tradable_symbols)}")
            
            # 步骤4: 调用策略回调函数（与货币对无关的计算）
            self.call_strategy_callback('before_loop', tradable_symbols)

            # 步骤3: 批量并行获取所有交易对的 OHLCV 数据
            timeframe = self.get_timeframe()
            ohlcv_data = fetch_ohlcv_batch_sync(
                self.exchange_service,
                tradable_symbols,
                timeframe,
                limit=settings.DEFAULT_OHLCV_LIMIT,
                max_workers=5
            )
            logger.info(f"批量获取 OHLCV 数据完成: {sum(1 for v in ohlcv_data.values() if v is not None)}/{len(tradable_symbols)} 成功")

            # 步骤5: 对每个交易对进行分析
            # 步骤6: 更新订单状态（移到循环外，只需执行一次）
            self.update_order_status()

            # 将持仓按 symbol 分组（优化：避免循环内重复遍历）
            positions_by_symbol: Dict[str, List[Position]] = {}
            for pos in open_positions:
                if pos.symbol not in positions_by_symbol:
                    positions_by_symbol[pos.symbol] = []
                positions_by_symbol[pos.symbol].append(pos)

            for symbol in tradable_symbols:
                try:
                    # 从批量获取的结果中取数据
                    dataframe = ohlcv_data.get(symbol)
                    if dataframe is None or dataframe.empty:
                        continue

                    # 步骤5: 分析策略
                    analysis_result = self.analyze_strategy(symbol, dataframe)

                    # 步骤7: 验证并平仓
                    self.verify_and_close_positions(symbol, analysis_result)

                    # 步骤8: 仓位调整（使用预分组的持仓，过滤已关闭的）
                    symbol_positions = [
                        pos for pos in positions_by_symbol.get(symbol, [])
                        if pos.is_open
                    ]
                    for position in symbol_positions:
                        self.adjust_position_size(position)

                    # 步骤9: 验证并开仓
                    self.verify_and_open_positions(symbol, analysis_result)

                except Exception as e:
                    logger.error(f"处理交易对 {symbol} 失败: {e}")
                    continue
            
            # 调用策略回调函数（循环结束）
            self.call_strategy_callback('after_loop', tradable_symbols)
            
        except Exception as e:
            # 详细记录交易循环异常信息
            exception_type = type(e).__name__
            exception_message = str(e)
            user_strategy_id = self.user_strategy.id if self.user_strategy else '未知'
            logger.error(
                f"交易循环执行异常终止 - "
                f"策略ID: {user_strategy_id}, "
                f"异常类型: {exception_type}, "
                f"异常消息: {exception_message}",
                exc_info=True
            )
            raise

