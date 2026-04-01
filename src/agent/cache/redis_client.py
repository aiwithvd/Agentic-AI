"""Redis connection pool, sliding-window rate limiter, and response cache."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

import redis.asyncio as aioredis

from agent.settings import get_settings

# Module-level pool — initialised once during lifespan startup
_redis_pool: Optional[aioredis.ConnectionPool] = None


def get_redis_pool() -> aioredis.ConnectionPool:
    """Return the module-level Redis connection pool."""
    global _redis_pool
    if _redis_pool is None:
        settings = get_settings()
        _redis_pool = aioredis.ConnectionPool.from_url(
            str(settings.redis_url),
            max_connections=settings.redis_max_connections,
            decode_responses=True,
        )
    return _redis_pool


def get_redis_client() -> aioredis.Redis:
    """Return a Redis client that shares the global connection pool."""
    return aioredis.Redis(connection_pool=get_redis_pool())


async def close_redis_pool() -> None:
    """Disconnect the Redis connection pool on application shutdown."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None


# ── Sliding-window rate limiter ───────────────────────────────────────────────
# Uses a Redis sorted set where each member is the request timestamp (ms).
# The Lua script is executed atomically, preventing TOCTOU races across
# multiple API workers.
_RATE_LIMIT_SCRIPT = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
local oldest = now - window * 1000

redis.call('ZREMRANGEBYSCORE', key, '-inf', oldest)
local count = redis.call('ZCARD', key)
if count >= limit then
    return 0
end
redis.call('ZADD', key, now, now)
redis.call('PEXPIRE', key, window * 1000)
return 1
"""


async def check_rate_limit(client_ip: str) -> bool:
    """Return True if the request is allowed, False if limit is exceeded."""
    settings = get_settings()
    client = get_redis_client()
    now_ms = int(time.time() * 1000)
    key = f"rate_limit:{client_ip}"
    result: int = await client.eval(  # type: ignore[attr-defined]
        _RATE_LIMIT_SCRIPT,
        1,
        key,
        now_ms,
        settings.rate_limit_window_seconds,
        settings.rate_limit_requests,
    )
    return bool(result)


# ── Response cache ────────────────────────────────────────────────────────────

def _cache_key(thread_id: str, user_input: str) -> str:
    """Derive a deterministic cache key from thread_id + user input."""
    payload = json.dumps(
        {"thread_id": thread_id, "input": user_input}, sort_keys=True
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"response_cache:{digest}"


async def get_cached_response(
    thread_id: str, user_input: str
) -> Optional[Any]:
    """Return a cached response dict or None on cache miss."""
    client = get_redis_client()
    raw = await client.get(_cache_key(thread_id, user_input))
    if raw is None:
        return None
    return json.loads(raw)


async def set_cached_response(
    thread_id: str, user_input: str, response: Any
) -> None:
    """Persist a response to cache with the configured TTL."""
    settings = get_settings()
    client = get_redis_client()
    await client.setex(
        _cache_key(thread_id, user_input),
        settings.cache_ttl_seconds,
        json.dumps(response),
    )
