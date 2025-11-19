"""
数据库连接和会话管理
"""
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool, NullPool
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# 根据数据库类型配置连接池
# 多用户场景下，需要支持大量并发策略
if "sqlite" in settings.DATABASE_URL:
    # SQLite 使用 StaticPool，适合多线程环境
    # StaticPool 会为每个线程创建独立的连接，避免连接池溢出
    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=StaticPool,
        connect_args={
            "check_same_thread": False,
            "timeout": 30  # SQLite 连接超时
        },
        pool_pre_ping=True,  # 连接前检查连接是否有效
        echo=False
    )
    logger.info("使用 SQLite 数据库，配置为 StaticPool（多线程安全）")
else:
    # PostgreSQL/MySQL 等使用连接池
    # 多用户场景：假设每个用户平均3个策略，10个用户需要30个连接
    # 设置更大的连接池以支持多用户并发
    pool_size = getattr(settings, 'DB_POOL_SIZE', 50)  # 基础连接池大小
    max_overflow = getattr(settings, 'DB_MAX_OVERFLOW', 50)  # 溢出连接数（总连接数可达100）
    
    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=60,  # 连接超时时间（秒）
        pool_recycle=3600,  # 连接回收时间（秒），1小时
        pool_pre_ping=True,  # 连接前检查连接是否有效
        echo=False
    )
    logger.info(f"使用 {settings.DATABASE_URL.split('://')[0]} 数据库，连接池大小: {pool_size}, 最大溢出: {max_overflow}")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """获取数据库会话（用于FastAPI依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session():
    """
    获取数据库会话（用于非FastAPI场景）
    注意：使用后必须调用 close() 关闭会话
    
    建议使用上下文管理器模式：
    with get_db_session() as db:
        # 使用 db
        pass
    """
    return SessionLocal()


class DBSessionManager:
    """
    数据库会话上下文管理器
    确保会话在使用后正确关闭，避免连接泄漏
    """
    def __init__(self):
        self.db = None
    
    def __enter__(self):
        self.db = SessionLocal()
        return self.db
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.db is not None:
            try:
                if exc_type is not None:
                    self.db.rollback()
                else:
                    self.db.commit()
            except Exception as e:
                logger.error(f"数据库会话提交/回滚失败: {e}", exc_info=True)
                if self.db is not None:
                    self.db.rollback()
            finally:
                try:
                    self.db.close()
                except Exception as e:
                    logger.error(f"关闭数据库会话失败: {e}", exc_info=True)
        return False  # 不抑制异常


def get_db_context():
    """
    获取数据库会话上下文管理器
    使用示例：
        with get_db_context() as db:
            # 使用 db 进行数据库操作
            pass
    """
    return DBSessionManager()

