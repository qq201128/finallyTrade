"""
用户服务
"""
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.models.user import User
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# 配置密码上下文，使用 bcrypt 算法
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,  # bcrypt 轮数
    bcrypt__ident="2b"  # 使用 2b 标识符（更兼容）
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"密码验证失败: {e}")
        return False


def get_password_hash(password: str) -> str:
    """加密密码"""
    try:
        # bcrypt 限制密码不能超过 72 字节
        password_bytes = password.encode('utf-8')
        if len(password_bytes) > 72:
            # 如果超过 72 字节，截断（这种情况很少见）
            password = password_bytes[:72].decode('utf-8', errors='ignore')
        return pwd_context.hash(password)
    except Exception as e:
        logger.error(f"密码哈希失败: {e}")
        raise


def get_user(db: Session, user_id: int) -> Optional[User]:
    """根据ID获取用户"""
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """根据用户名获取用户"""
    return db.query(User).filter(User.username == username).first()


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """根据邮箱获取用户"""
    return db.query(User).filter(User.email == email).first()


def create_user(db: Session, username: str, email: str, password: str) -> User:
    """创建用户"""
    hashed_password = get_password_hash(password)
    user = User(
        username=username,
        email=email,
        hashed_password=hashed_password
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"创建用户: {username}")
    return user


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """验证用户"""
    try:
        user = get_user_by_username(db, username)
        if not user:
            logger.debug(f"用户不存在: {username}")
            return None
        if not verify_password(password, user.hashed_password):
            logger.debug(f"密码验证失败: {username}")
            return None
        logger.debug(f"用户验证成功: {username}")
        return user
    except Exception as e:
        logger.error(f"用户验证异常: {e}", exc_info=True)
        return None

