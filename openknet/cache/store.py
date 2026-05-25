from __future__ import annotations
import pickle
import threading
from typing import Any

from loguru import logger

from ..config import settings


class CacheStore:
    """
    Async key-value cache.
    Uses Redis when `settings.redis_url` is set; falls back to a process-local
    dict otherwise.  All values are serialised with pickle so complex objects
    (ProjectIndex, numpy arrays) round-trip correctly.
    """

    def __init__(self) -> None:
        self._redis = None
        self._mem: dict[str, bytes] = {}
        self._lock = threading.Lock()

    async def connect(self) -> None:
        if not settings.redis_url:
            logger.debug("No REDIS_URL — using in-memory cache")
            return
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                settings.redis_url, encoding="utf-8", decode_responses=False
            )
            await self._redis.ping()
            logger.info(f"Redis cache connected: {settings.redis_url}")
        except Exception as exc:
            logger.warning(f"Redis unavailable ({exc}); using in-memory fallback")
            self._redis = None

    async def get(self, key: str) -> Any | None:
        raw: bytes | None = None
        if self._redis:
            raw = await self._redis.get(key)
        else:
            with self._lock:
                raw = self._mem.get(key)
        return pickle.loads(raw) if raw is not None else None

    async def set(self, key: str, value: Any, ttl: int = 7200) -> None:
        raw = pickle.dumps(value)
        if self._redis:
            await self._redis.setex(key, ttl, raw)
        else:
            with self._lock:
                self._mem[key] = raw

    async def delete(self, key: str) -> None:
        if self._redis:
            await self._redis.delete(key)
        else:
            with self._lock:
                self._mem.pop(key, None)

    @property
    def backend(self) -> str:
        return "redis" if self._redis else "memory"


# Singleton
_store: CacheStore | None = None


def get_cache() -> CacheStore:
    global _store
    if _store is None:
        _store = CacheStore()
    return _store
