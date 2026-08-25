"""Redis client and the notification queue.

Also backs the pipeline poller's cross-worker lock, so a multi-worker deployment
runs the poll loop once rather than once per worker.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from app.config import settings

FEATURE_CACHE_TTL = 300


def feature_cache_key(org_id: int) -> str:
    """Return the Redis cache key for an organisation's feature flags.

    Args:
        org_id: The organisation ID.

    Returns:
        Redis key string.
    """
    return f"features:{org_id}"


async def get_redis() -> aioredis.Redis:
    """Return an async Redis client connected to settings.redis_url.

    Returns:
        An async Redis client instance.
    """
    return aioredis.from_url(settings.redis_url, decode_responses=True)
