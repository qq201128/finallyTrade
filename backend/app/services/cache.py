"""
通用缓存服务：支持内存与Redis后端
"""
import asyncio
import logging
import pickle
import time
from typing import Optional, Any, Dict, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from redis import asyncio as redis_async  # type: ignore
except ImportError:  # pragma: no cover - 可选依赖
    redis_async = None


class BaseCacheBackend:
    async def get(self, key: str) -> Optional[bytes]:
        raise NotImplementedError

    async def set(self, key: str, value: bytes, ttl: Optional[float] = None):
        raise NotImplementedError

    async def delete(self, key: str):
        raise NotImplementedError


class MemoryCacheBackend(BaseCacheBackend):
    """简单的内存缓存，进程内可用"""

    def __init__(self):
        self._store: Dict[str, Tuple[bytes, Optional[float]]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[bytes]:
        async with self._lock:
            value = self._store.get(key)
            if not value:
                return None
            payload, expiry = value
            if expiry and expiry < time.monotonic():
                self._store.pop(key, None)
                return None
            return payload

    async def set(self, key: str, value: bytes, ttl: Optional[float] = None):
        expiry = None
        if ttl and ttl > 0:
            expiry = time.monotonic() + ttl
        async with self._lock:
            self._store[key] = (value, expiry)

    async def delete(self, key: str):
        async with self._lock:
            self._store.pop(key, None)


class RedisCacheBackend(BaseCacheBackend):
    """Redis缓存（需要redis>=4.2，支持asyncio）"""

    def __init__(self, url: str):
        if not redis_async:
            raise RuntimeError("未安装 redis[async]，无法使用 Redis 缓存")
        self._url = url
        self._client: Optional[redis_async.Redis] = None
        self._lock = asyncio.Lock()

    async def _get_client(self):
        if self._client:
            return self._client
        async with self._lock:
            if self._client:
                return self._client
            self._client = redis_async.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=False,
                health_check_interval=30,
            )
            return self._client

    async def get(self, key: str) -> Optional[bytes]:
        client = await self._get_client()
        try:
            return await client.get(key)
        except Exception as exc:  # pragma: no cover - 网络异常
            logger.error(f"Redis缓存读取失败: {exc}")
            return None

    async def set(self, key: str, value: bytes, ttl: Optional[float] = None):
        client = await self._get_client()
        try:
            if ttl and ttl > 0:
                await client.setex(key, int(max(1, ttl)), value)
            else:
                await client.set(key, value)
        except Exception as exc:  # pragma: no cover
            logger.error(f"Redis缓存写入失败: {exc}")

    async def delete(self, key: str):
        client = await self._get_client()
        try:
            await client.delete(key)
        except Exception as exc:  # pragma: no cover
            logger.error(f"Redis缓存删除失败: {exc}")


class CacheService:
    """统一缓存入口"""

    def __init__(self):
        self.backend: BaseCacheBackend = self._init_backend()

    def _init_backend(self) -> BaseCacheBackend:
        backend_type = (settings.CACHE_BACKEND or "memory").lower()
        if backend_type == "redis" and settings.REDIS_URL:
            try:
                logger.info("使用 Redis 作为缓存后端")
                return RedisCacheBackend(settings.REDIS_URL)
            except Exception as exc:
                logger.warning(f"Redis 初始化失败，回退到内存缓存: {exc}")
        logger.info("使用内存缓存后端")
        return MemoryCacheBackend()

    async def get(self, key: str) -> Any:
        data = await self.backend.get(key)
        if data is None:
            return None
        try:
            return pickle.loads(data)
        except Exception as exc:  # pragma: no cover
            logger.error(f"缓存数据反序列化失败: {exc}")
            return None

    async def set(self, key: str, value: Any, ttl: Optional[float] = None):
        try:
            payload = pickle.dumps(value)
            await self.backend.set(key, payload, ttl or settings.CACHE_DEFAULT_TTL)
        except Exception as exc:  # pragma: no cover
            logger.error(f"缓存数据序列化失败: {exc}")

    async def delete(self, key: str):
        await self.backend.delete(key)


cache_service = CacheService()


