from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_HIT_LOG = "response_cache: hit for key '%s'"
_CACHE_MISS_LOG = "response_cache: miss for key '%s'"


class ResponseCache:
    """Async in-memory TTL cache for API responses.

    Thread-safe via asyncio.Lock. Keys are strings (typically endpoint + query params).
    Values expire after ttl_seconds. Use module-level `response_cache` singleton.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expires_at)
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                logger.debug(_CACHE_MISS_LOG, key)
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                logger.debug(_CACHE_MISS_LOG, key)
                return None
            logger.debug(_CACHE_HIT_LOG, key)
            return value

    async def set(self, key: str, value: Any, ttl: int) -> None:
        async with self._lock:
            self._store[key] = (value, time.monotonic() + ttl)

    async def invalidate_all(self) -> None:
        async with self._lock:
            self._store.clear()


response_cache = ResponseCache()
