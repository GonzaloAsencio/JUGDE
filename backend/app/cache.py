import hashlib
import json
import logging

logger = logging.getLogger(__name__)

_redis_client = None


def init_redis(url: str, token: str):
    """Create and store the Upstash Redis client. Call once at startup."""
    global _redis_client
    try:
        from upstash_redis import Redis  # type: ignore[import-untyped]

        _redis_client = Redis(url=url, token=token)
        logger.info("Upstash Redis client initialised.")
    except Exception as e:
        logger.warning("Redis init failed — cache disabled: %s", e)
        _redis_client = None


def close_redis() -> None:
    """No-op for upstash-redis (HTTP client, no persistent connections)."""
    global _redis_client
    _redis_client = None


def make_cache_key(question: str, corpus_version: str) -> str:
    """Derive a deterministic cache key.

    Key = SHA-256( lowercase(strip(question)) + "|" + corpus_version )
    card_mentions intentionally excluded in v1 (see ADR-8).
    """
    normalized = question.strip().lower()
    payload = json.dumps({"q": normalized, "cv": corpus_version}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


async def get_cached(key: str) -> str | None:
    """Return the cached JSON string for *key*, or None on miss/error."""
    if _redis_client is None:
        return None
    try:
        value = _redis_client.get(key)
        return value if isinstance(value, str) else None
    except Exception as e:
        logger.warning("Redis GET failed (cache miss): %s", e)
        return None


async def set_cached(key: str, value: str, ttl: int) -> None:
    """Store *value* under *key* with *ttl* seconds. No-op on error."""
    if _redis_client is None:
        return
    try:
        _redis_client.set(key, value, ex=ttl)
    except Exception as e:
        logger.warning("Redis SET failed (caching skipped): %s", e)
