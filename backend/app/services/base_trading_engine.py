"""
交易引擎基类 - 提取 TradingEngine 和 BidirectionalTradingEngine 的公共代码
"""
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import Position, Order, UserStrategy, PnLRecord
from app.models.trade import OrderStatus, OrderSide, OrderType
from app.services.exchange_service import ExchangeService
from app.services.strategy_engine import StrategyEngine
from app.services.ohlcv_cache import get_ohlcv_cache
from app.core.config import settings
from app.utils.timeframe import parse_timeframe, get_candle_start_timestamp
from app.utils.pnl import calculate_unrealized_pnl, calculate_realized_pnl, calculate_pnl_percentage_from_prices
from app.utils.websocket_push import push_position_update_sync, build_position_message
import pandas as pd

logger = logging.getLogger(__name__)


class BaseTradingEngine(ABC):
    """交易引擎基类"""

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
        self.db = db
        self.user_strategy = user_strategy
        self.exchange_service = exchange_service
        self.strategy_engine = strategy_engine
        self.strategy_module = None
        # 使用全局共享的OHLCV缓存
        self.ohlcv_cache = get_ohlcv_cache(ttl_seconds=settings.CACHE_OHLCV_TTL)
        # 价格缓存：在单次交易循环中缓存价格，避免重复 API 调用
        self._price_cache: Dict[str, float] = {}

        # 加载策略
        self._load_strategy()

    def _get_cached_price(self, symbol: str) -> Optional[float]:
        """获取缓存的价格，如果没有则从交易所获取并缓存"""
        if symbol in self._price_cache:
            return self._price_cache[symbol]

        try:
            ticker = self.exchange_service.exchange.fetch_ticker(symbol)
            price = ticker.get('last', 0)
            if price > 0:
                self._price_cache[symbol] = price
                return price
        except Exception as e:
            logger.warning(f"获取 {symbol} 价格失败: {e}")
        return None

    def _clear_price_cache(self):
        """清空价格缓存（在每次交易循环开始时调用）"""
        self._price_cache.clear()

    def _load_strategy(self):
        """加载策略模块"""
        try:
            self.strategy_module = self.strategy_engine.load_strategy(
                self.user_strategy.strategy.name,
                self.user_strategy.strategy.file_path
            )
        except Exception as e:
            logger.error(f"加载策略失败: {e}")
            raise

    def get_timeframe(self) -> str:
        """获取时间周期"""
        return self.user_strategy.timeframe if self.user_strategy.timeframe else '1h'

    def get_leverage(self) -> int:
        """获取杠杆倍数"""
        leverage = self.user_strategy.config.get('leverage', 1) or 1
        return max(1, leverage)

    def get_margin_amount(self) -> float:
        """获取保证金金额"""
        try:
            return float(self.user_strategy.trade_amount) if self.user_strategy.trade_amount else settings.DEFAULT_MARGIN_AMOUNT
        except (ValueError, TypeError):
            logger.warning(f"无法解析交易数量配置 '{self.user_strategy.trade_amount}'，使用默认值 {settings.DEFAULT_MARGIN_AMOUNT} USDT")
            return settings.DEFAULT_MARGIN_AMOUNT

    def get_tradable_symbols(self) -> List[str]:
        """获取可交易的交易对列表"""
        try:
            symbols = self.exchange_service.get_tradable_symbols()
            if self.user_strategy.symbols and len(self.user_strategy.symbols) > 0:
                allowed_symbols = self.user_strategy.symbols
                symbols = [s for s in symbols if s in allowed_symbols]
                # logger.info(f"使用配置的币种列表: {allowed_symbols}, 过滤后: {len(symbols)} 个交易对")
            return symbols
        except Exception as e:
            logger.error(f"获取可交易对列表失败: {e}")
            return []

    def fetch_ohlcv_data(self, symbol: str, timeframe: str = None,
                         limit: int = 100) -> Optional[pd.DataFrame]:
        """
        获取OHLCV数据（使用全局共享缓存）
        """
        if timeframe is None:
            timeframe = self.get_timeframe()

        # 从全局共享缓存获取
        exchange_name = self.exchange_service.exchange_name
        cached_df = self.ohlcv_cache.get(exchange_name, symbol, timeframe)
        if cached_df is not None:
            logger.debug(f"从共享缓存获取OHLCV数据: {exchange_name}:{symbol}:{timeframe}")
            return cached_df

        # 缓存未命中，从交易所获取
        try:
            logger.debug(f"从交易所获取OHLCV数据: {exchange_name}:{symbol}:{timeframe}")
            ohlcv = self.exchange_service.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv:
                return None

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)

            # 存储到全局共享缓存
            self.ohlcv_cache.set(exchange_name, symbol, timeframe, df)

            return df
        except Exception as e:
            logger.error(f"获取 {symbol} OHLCV数据失败: {e}")
            return None

    def call_strategy_callback(self, callback_name: str, *args, **kwargs):
        """调用策略回调函数"""
        if self.strategy_module:
            return self.strategy_engine.call_strategy_callback(
                self.strategy_module, callback_name, *args, **kwargs
            )
        return None

    def update_order_status(self):
        """更新订单状态"""
        try:
            pending_orders = self.db.query(Order).filter(
                Order.user_id == self.user_strategy.user_id,
                Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED])
            ).all()

            for order in pending_orders:
                try:
                    exchange_order = self.exchange_service.fetch_order(
                        order.exchange_order_id, order.symbol
                    )

                    order.status = OrderStatus(exchange_order.get('status', 'pending'))
                    order.filled = exchange_order.get('filled', 0.0)
                    order.cost = exchange_order.get('cost', 0.0)
                    order.fee = exchange_order.get('fee', {}).get('cost', 0.0)

                    if order.status == OrderStatus.FILLED:
                        order.filled_at = datetime.now()
                        self.order_filled(order, exchange_order)

                    self.db.commit()
                except Exception as e:
                    logger.error(f"更新订单 {order.id} 状态失败: {e}")
                    continue
        except Exception as e:
            logger.error(f"更新订单状态失败: {e}")

    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        try:
            ticker = self.exchange_service.exchange.fetch_ticker(symbol)
            current_price = ticker.get('last', 0)
            if current_price == 0:
                ohlcv = self.exchange_service.fetch_ohlcv(symbol, self.get_timeframe(), limit=1)
                if ohlcv and len(ohlcv) > 0:
                    current_price = ohlcv[-1][4]
            return current_price if current_price > 0 else None
        except Exception as e:
            logger.warning(f"获取 {symbol} 价格失败: {e}")
            return None

    def create_pnl_record(self, order: Order, position: Position, exit_price: float,
                          realized_pnl: float) -> PnLRecord:
        """创建盈亏记录"""
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
            pnl_percentage=calculate_pnl_percentage_from_prices(
                position.entry_price, exit_price, order.filled, effective_leverage, position.side
            )
        )
        return pnl_record

    def push_position_closed(self, position: Position, exit_price: float):
        """推送持仓关闭消息"""
        message = build_position_message(
            position_id=position.id,
            symbol=position.symbol,
            side=position.side,
            size=0,
            entry_price=position.entry_price,
            current_price=exit_price,
            unrealized_pnl=0,
            leverage=position.leverage or 1,
            margin_used=0,
            pnl_percentage=0,
            is_open=False
        )
        push_position_update_sync(message, position.user_id)

    def create_simulated_order(self, user_id: int, symbol: str, side: OrderSide,
                                order_type: OrderType, amount: float, price: float = None,
                                position_id: int = None, cost: float = None) -> Order:
        """创建模拟订单"""
        order = Order(
            user_id=user_id,
            position_id=position_id,
            exchange_order_id=f"SIM_{datetime.now().timestamp()}",
            symbol=symbol,
            side=side,
            type=order_type,
            amount=amount,
            price=price,
            filled=amount,
            cost=cost or (price * amount if price else 0),
            status=OrderStatus.FILLED,
            filled_at=datetime.now()
        )
        return order

    def _get_candle_start_timestamp(self, timestamp: datetime, timeframe: str) -> datetime:
        """获取K线周期的开始时间戳"""
        return get_candle_start_timestamp(timestamp, timeframe)

    def _get_last_close_candle_timestamp(self, symbol: str, side: str = None) -> Optional[datetime]:
        """
        获取指定交易对最后平仓的K线周期时间戳

        Args:
            symbol: 交易对
            side: 方向（可选，用于双向交易）

        Returns:
            最后平仓的K线周期开始时间戳，如果没有则返回None
        """
        if not self.user_strategy.config:
            return None

        last_close_times = self.user_strategy.config.get('last_close_candle_times', {})
        # 生成 key：如果有 side 则使用 symbol_side 格式，否则只使用 symbol
        key = f"{symbol}_{side}" if side else symbol
        timestamp_str = last_close_times.get(key)
        if timestamp_str:
            try:
                return datetime.fromisoformat(timestamp_str)
            except (ValueError, TypeError):
                return None
        return None

    def _set_last_close_candle_timestamp(self, symbol: str, timestamp: datetime, side: str = None):
        """
        设置指定交易对最后平仓的K线周期时间戳

        Args:
            symbol: 交易对
            timestamp: K线周期开始时间戳
            side: 方向（可选，用于双向交易）
        """
        if not self.user_strategy.config:
            self.user_strategy.config = {}

        if 'last_close_candle_times' not in self.user_strategy.config:
            self.user_strategy.config['last_close_candle_times'] = {}

        # 生成 key：如果有 side 则使用 symbol_side 格式，否则只使用 symbol
        key = f"{symbol}_{side}" if side else symbol
        self.user_strategy.config['last_close_candle_times'][key] = timestamp.isoformat()
        self.db.commit()

    def get_entry_price_from_order(self, order: Order) -> float:
        """
        从订单获取入场价格

        Args:
            order: 订单对象

        Returns:
            入场价格
        """
        position_size = order.filled if order.filled and order.filled > 0 else order.amount

        # 优先使用订单价格
        if order.price and order.price > 0:
            return order.price

        # 其次从成本计算
        if order.cost and order.cost > 0 and position_size > 0:
            return order.cost / position_size

        # 最后尝试从交易所获取
        try:
            ticker = self.exchange_service.exchange.fetch_ticker(order.symbol)
            entry_price = ticker.get('last', 0)
            if entry_price > 0:
                return entry_price
        except Exception as e:
            logger.warning(f"获取 {order.symbol} 价格失败: {e}")

        return 0

    def get_position_leverage(self, symbol: str) -> int:
        """
        获取持仓杠杆倍数

        Args:
            symbol: 交易对

        Returns:
            杠杆倍数
        """
        # 从配置获取默认杠杆
        leverage = self.user_strategy.config.get('leverage', settings.DEFAULT_LEVERAGE) or settings.DEFAULT_LEVERAGE
        if leverage <= 0:
            leverage = 1

        # 尝试从交易所获取实际杠杆
        try:
            positions = self.exchange_service.fetch_positions(symbol)
            if positions:
                for pos in positions:
                    if pos.get('symbol') == symbol:
                        exchange_leverage = pos.get('leverage', leverage) or leverage
                        if exchange_leverage > 0:
                            return exchange_leverage
        except Exception as e:
            logger.debug(f"获取 {symbol} 杠杆信息失败: {e}，使用配置值 {leverage}x")

        return leverage

    def calculate_position_amount(self, symbol: str, current_price: float = None) -> float:
        """
        计算开仓数量

        Args:
            symbol: 交易对
            current_price: 当前价格（可选，如果不提供则自动获取）

        Returns:
            开仓数量（币种数量）
        """
        margin_amount = self.get_margin_amount()
        leverage = self.get_leverage()
        notional_value = margin_amount * leverage

        # 获取当前价格
        if not current_price:
            current_price = self._get_cached_price(symbol)

        if not current_price or current_price <= 0:
            logger.error(f"无法获取 {symbol} 的价格，无法计算开仓数量")
            return 0

        # 币种数量 = 名义价值 / 当前价格
        amount = notional_value / current_price
        return amount

    @abstractmethod
    def get_open_positions(self, symbol: str = None, side: str = None) -> List[Position]:
        """获取未平仓交易"""
        pass

    @abstractmethod
    def analyze_strategy(self, symbol: str, dataframe: pd.DataFrame) -> Dict[str, Any]:
        """分析策略"""
        pass

    @abstractmethod
    def order_filled(self, order: Order, exchange_order: Dict):
        """订单成交回调"""
        pass

    @abstractmethod
    def verify_and_close_positions(self, symbol: str, analysis_result: Dict):
        """验证并平仓"""
        pass

    @abstractmethod
    def verify_and_open_positions(self, symbol: str, analysis_result: Dict):
        """验证并开仓"""
        pass

    @abstractmethod
    def adjust_position_size(self, position: Position):
        """仓位调整"""
        pass

    @abstractmethod
    def update_positions_prices(self):
        """更新持仓价格"""
        pass

    @abstractmethod
    def run_trading_loop(self):
        """执行交易循环"""
        pass
