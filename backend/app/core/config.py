"""
应用配置
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str = "Trading System"
    DEBUG: bool = True
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30 * 24 * 60  # 30天
    
    # 数据库配置
    DATABASE_URL: str = "sqlite:///./trading_system.db"
    
    # 数据库连接池配置（可选，用于非SQLite数据库）
    DB_POOL_SIZE: int = 50  # 连接池大小
    DB_MAX_OVERFLOW: int = 50  # 最大溢出连接数
    
    # 策略文件目录
    STRATEGIES_DIR: str = "./app/strategies"
    
    # CCXT代理配置（可选）
    PROXY_URL: Optional[str] = None
    HTTP_PROXY: Optional[str] = None
    HTTPS_PROXY: Optional[str] = None
    SOCKS_PROXY: Optional[str] = None
    
    # WebSocket配置
    WS_ENABLED: bool = True
    FAILSAFE_POLLING_MODE: bool = False  # 当WebSocket不可靠时强制使用轮询
    WS_POLLING_INTERVAL: float = 2.0  # 轮询间隔秒
    
    # 缓存与Redis配置
    CACHE_BACKEND: str = "memory"  # memory 或 redis
    REDIS_URL: Optional[str] = None
    CACHE_DEFAULT_TTL: int = 60
    CACHE_MARKETS_TTL: int = 300
    CACHE_TRADABLE_TTL: int = 120
    CACHE_TICKER_TTL: float = 1.0
    CACHE_OHLCV_TTL: int = 300  # OHLCV数据缓存有效期（秒），默认5分钟
    
    # 监控与降级
    MONITORING_ENABLED: bool = False
    MONITORING_NAMESPACE: str = "trading_app"
    MONITORING_SAMPLE_RATE: float = 1.0  # 0~1之间
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

