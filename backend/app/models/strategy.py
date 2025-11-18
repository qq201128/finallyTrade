"""
策略模型
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, JSON, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Strategy(Base):
    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    description = Column(Text)
    file_path = Column(String, nullable=False)  # 策略文件路径
    is_active = Column(Boolean, default=True)
    config = Column(JSON, default={})  # 策略配置参数
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    user_strategies = relationship("UserStrategy", back_populates="strategy", cascade="all, delete-orphan")


class UserStrategy(Base):
    __tablename__ = "user_strategies"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    is_enabled = Column(Boolean, default=True)  # 用户是否启用该策略
    config = Column(JSON, default={})  # 用户自定义策略配置
    exchange = Column(String, nullable=False)  # 交易所名称
    api_key = Column(String)  # 用户交易所API Key（加密存储）
    api_secret = Column(String)  # 用户交易所API Secret（加密存储）
    
    # 新增配置字段
    symbols = Column(JSON, default=[])  # 币种列表（可选多个，只支持永续合约）
    timeframe = Column(String, default=None)  # 时间周期（K线周期），如 '1m', '5m', '15m', '1h', '4h', '1d'（可选）
    trade_amount = Column(String, default=None)  # 每笔交易使用的加密货币数量（字符串类型，支持小数）（可选）
    is_simulated = Column(Boolean, default=False)  # 是否模拟运行（模拟模式下不实际下单）
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    user = relationship("User", back_populates="user_strategies")
    strategy = relationship("Strategy", back_populates="user_strategies")
    positions = relationship("Position", back_populates="user_strategy", cascade="all, delete-orphan")
    history_records = relationship("StrategyHistory", back_populates="user_strategy", cascade="all, delete-orphan")


class StrategyHistory(Base):
    """策略历史记录 - 记录每次启动策略的运行情况"""
    __tablename__ = "strategy_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_strategy_id = Column(Integer, ForeignKey("user_strategies.id"), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)  # 启动时间
    stopped_at = Column(DateTime(timezone=True))  # 停止时间（如果还在运行则为None）
    total_realized_pnl = Column(Float, default=0.0)  # 该期间的总已实现盈亏
    total_trades = Column(Integer, default=0)  # 该期间的总交易次数
    total_positions = Column(Integer, default=0)  # 该期间的总持仓数
    is_running = Column(Boolean, default=True)  # 是否还在运行中
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    user_strategy = relationship("UserStrategy", back_populates="history_records")

