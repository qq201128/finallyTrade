"""
数据库连接和会话管理
"""
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool, StaticPool, NullPool
from app.core.config import settings
import logging
import threading

logger = logging.getLogger(__name__)

# 根据数据库类型配置连接池
# 多用户场景下，需要支持大量并发策略
if "sqlite" in settings.DATABASE_URL:
    # SQLite 多线程解决方案：
    # 1. 使用 NullPool（不使用连接池），每次请求创建新连接
    # 2. 配合 scoped_session 确保每个线程有独立的会话
    # 这样可以避免 "bad parameter or other API misuse" 错误
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        """设置SQLite的PRAGMA参数，优化多线程并发性能"""
        try:
            cursor = dbapi_conn.cursor()
            # 启用WAL模式（Write-Ahead Logging），提高并发性能
            cursor.execute("PRAGMA journal_mode=WAL")
            # 设置忙等待超时（毫秒），避免数据库锁定
            cursor.execute("PRAGMA busy_timeout=30000")  # 30秒
            # 启用外键约束
            cursor.execute("PRAGMA foreign_keys=ON")
            # 设置同步模式为NORMAL（WAL模式下推荐）
            cursor.execute("PRAGMA synchronous=NORMAL")
            # 设置缓存大小（64MB），提高性能
            cursor.execute("PRAGMA cache_size=-65536")  # 64MB
            cursor.close()
        except Exception as e:
            logger.warning(f"设置SQLite PRAGMA失败: {e}")

    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,  # 不使用连接池，每次创建新连接
        connect_args={
            "check_same_thread": False,  # 允许多线程访问
            "timeout": 30  # SQLite 连接超时
        },
        echo=False
    )
    # 注册事件监听器，在连接创建时设置PRAGMA
    event.listen(engine, "connect", _set_sqlite_pragma)
    logger.info("使用 SQLite 数据库，配置为 NullPool（多线程安全），已启用WAL模式")
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

# 创建线程本地的会话工厂
_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# 使用 scoped_session 确保每个线程有独立的会话实例
SessionLocal = scoped_session(_session_factory)

Base = declarative_base()


def get_db():
    """获取数据库会话（用于FastAPI依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        # scoped_session 需要调用 remove() 来清理线程本地会话
        SessionLocal.remove()


def get_db_session():
    """
    获取数据库会话（用于非FastAPI场景）
    注意：使用后必须调用 close() 或 SessionLocal.remove() 关闭会话

    建议使用上下文管理器模式：
    with get_db_context() as db:
        # 使用 db
        pass
    """
    return SessionLocal()


class DBSessionManager:
    """
    数据库会话上下文管理器
    确保会话在使用后正确关闭，避免连接泄漏
    针对SQLite多线程并发进行了优化
    """
    def __init__(self):
        self.db = None
        self.retry_count = 0
        self.max_retries = 3

    def __enter__(self):
        # 创建新的数据库会话（scoped_session 会自动管理线程本地会话）
        self.db = SessionLocal()
        return self.db

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.db is not None:
            try:
                if exc_type is not None:
                    # 发生异常时回滚
                    try:
                        self.db.rollback()
                    except Exception as rollback_error:
                        logger.warning(f"回滚数据库会话失败: {rollback_error}")
                else:
                    # 正常情况提交事务
                    try:
                        self.db.commit()
                    except Exception as commit_error:
                        # 如果是数据库锁定错误，尝试重试
                        error_str = str(commit_error).lower()
                        if "locked" in error_str or "database is locked" in error_str:
                            logger.warning(f"数据库锁定，尝试回滚后重试: {commit_error}")
                            try:
                                self.db.rollback()
                                # 等待一小段时间后重试提交
                                import time
                                time.sleep(0.1)
                                self.db.commit()
                            except Exception as retry_error:
                                logger.error(f"重试提交失败: {retry_error}")
                                self.db.rollback()
                        else:
                            logger.error(f"数据库会话提交失败: {commit_error}", exc_info=True)
                            self.db.rollback()
            except Exception as e:
                logger.error(f"数据库会话处理失败: {e}", exc_info=True)
                try:
                    if self.db is not None:
                        self.db.rollback()
                except Exception:
                    pass
            finally:
                try:
                    # 使用 scoped_session 的 remove() 方法清理线程本地会话
                    SessionLocal.remove()
                except Exception as e:
                    logger.error(f"清理数据库会话失败: {e}", exc_info=True)
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

