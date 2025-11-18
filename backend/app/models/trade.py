"""
交易相关模型
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class OrderSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, enum.Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELED = "canceled"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user_strategy_id = Column(Integer, ForeignKey("user_strategies.id"), nullable=False)
    symbol = Column(String, nullable=False)  # 交易对，如 BTC/USDT
    side = Column(String, nullable=False)  # long/short
    size = Column(Float, nullable=False)  # 持仓数量
    entry_price = Column(Float, nullable=False)  # 开仓价格
    current_price = Column(Float)  # 当前价格
    unrealized_pnl = Column(Float, default=0.0)  # 未实现盈亏
    leverage = Column(Integer, default=1)  # 杠杆倍数（如 10x, 20x）
    stop_loss = Column(Float)  # 止损价格
    take_profit = Column(Float)  # 止盈价格
    is_open = Column(Boolean, default=True)  # 是否持仓中
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True))
    
    # 关系
    user = relationship("User", back_populates="positions")
    user_strategy = relationship("UserStrategy", back_populates="positions")
    orders = relationship("Order", back_populates="position", cascade="all, delete-orphan")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=True)
    exchange_order_id = Column(String, unique=True, index=True)  # 交易所订单ID
    symbol = Column(String, nullable=False)
    side = Column(SQLEnum(OrderSide), nullable=False)
    type = Column(SQLEnum(OrderType), nullable=False)
    amount = Column(Float, nullable=False)
    price = Column(Float)  # 限价单价格
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.PENDING)
    filled = Column(Float, default=0.0)  # 已成交数量
    cost = Column(Float)  # 成交金额
    fee = Column(Float, default=0.0)  # 手续费
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    filled_at = Column(DateTime(timezone=True))
    
    # 关系
    user = relationship("User", back_populates="orders")
    position = relationship("Position", back_populates="orders")


class PnLRecord(Base):
    __tablename__ = "pnl_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user_strategy_id = Column(Integer, ForeignKey("user_strategies.id"), nullable=False)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False)
    symbol = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    size = Column(Float, nullable=False)
    realized_pnl = Column(Float, nullable=False)  # 已实现盈亏
    fee = Column(Float, default=0.0)
    pnl_percentage = Column(Float)  # 盈亏百分比
    closed_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 关系
    user = relationship("User")
    user_strategy = relationship("UserStrategy")
    position = relationship("Position")

