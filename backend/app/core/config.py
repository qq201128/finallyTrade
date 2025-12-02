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

    # 交易引擎配置
    DEFAULT_OHLCV_LIMIT: int = 100  # 默认获取K线数量
    DEFAULT_LEVERAGE: int = 1  # 默认杠杆倍数
    DEFAULT_MARGIN_AMOUNT: float = 0.001  # 默认保证金（USDT）
    DEFAULT_ROI_THRESHOLD: float = -0.1  # 默认止损ROI阈值（-10%）
    DEFAULT_LOOP_INTERVAL: int = 10  # 默认交易循环间隔（秒）
    OHLCV_FETCH_MAX_WORKERS: int = 5  # OHLCV 并行获取最大线程数
    OHLCV_FETCH_MAX_CONCURRENT: int = 5  # OHLCV 异步并行获取最大并发数

    # WebSocket 持仓推送配置
    WS_POSITIONS_CACHE_TTL: float = 10.0  # 持仓缓存有效期（秒）
    WS_BATCH_UPDATE_INTERVAL: float = 5.0  # 批量更新间隔（秒）
    WS_MAX_BATCH_SIZE: int = 50  # 每次批量更新最大数量

    # 价格缓存配置
    PRICE_CACHE_TTL: int = 10  # 价格缓存有效期（秒）
    PRICE_CACHE_MAX_SIZE: int = 1000  # 价格缓存最大条目数

    # 线程配置
    THREAD_STOP_TIMEOUT: int = 10  # 线程停止超时（秒）
    THREAD_MONITOR_INTERVAL: int = 60  # 线程监控间隔（秒）

    # 监控与降级
    MONITORING_ENABLED: bool = False
    MONITORING_NAMESPACE: str = "trading_app"
    MONITORING_SAMPLE_RATE: float = 1.0  # 0~1之间
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

