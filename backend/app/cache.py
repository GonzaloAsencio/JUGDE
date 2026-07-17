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


def is_enabled() -> bool:
    """True when a Redis client is live.

    The semantic cache (app/semantic_cache.py) gates its ANN query on this: the
    ANSWER lives in Redis, so with no Redis there is nothing a semantic hit
    could return — running the vector search would be pure waste. It also keeps
    scripts/eval.py byte-identical, since the harness deliberately never calls
    init_redis (every question must hit generation fresh).
    """
    return _redis_client is not None


def directive_key(card_mentions: list[str] | None = None, tags: list[str] | None = None) -> str:
    """Stable text key for the NON-SEMANTIC dimensions of a question: the
    caller's card_mentions and any @tags embedded in the prose.

    The semantic cache partitions on this so a nearest-neighbour match can never
    cross a directive boundary. It must stay in lockstep with what
    make_cache_key hashes: both sort the same inputs, so two questions the exact
    key treats as distinct can never be merged by the semantic one.
    """
    mentions = sorted(card_mentions) if card_mentions else []
    sorted_tags = sorted(tags) if tags else []
    return json.dumps({"m": mentions, "t": sorted_tags}, ensure_ascii=False, sort_keys=True)


def make_cache_key(question: str, corpus_version: str, card_mentions: list[str] | None = None, prompt_version: str = "v1") -> str:
    """Derive a deterministic cache key.

    Key = SHA-256({"q": normalize(question), "cv": corpus_version, "pv": prompt_version, "m": sorted(card_mentions)})

    Note: @tags are not hashed separately — they live inside the raw *question*
    text, so they already change the key. directive_key() surfaces them
    explicitly for the semantic cache, which embeds the tag-stripped question
    and therefore cannot see them any other way.
    """
    normalized = question.strip().lower()
    mentions = sorted(card_mentions) if card_mentions else []
    payload = json.dumps(
        {"q": normalized, "cv": corpus_version, "pv": prompt_version, "m": mentions},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def get_cached(key: str) -> str | None:
    """Return the cached JSON string for *key*, or None on miss/error.

    Synchronous: the Upstash client is an HTTP client with no async API, so an
    ``async def`` here never yielded to the event loop — it only masked a
    blocking call. The pipeline runs in FastAPI's threadpool (sync handler), so
    a plain blocking call is correct and honest about what happens.
    """
    if _redis_client is None:
        return None
    try:
        value = _redis_client.get(key)
        return value if isinstance(value, str) else None
    except Exception as e:
        logger.warning("Redis GET failed (cache miss): %s", e)
        return None


def set_cached(key: str, value: str, ttl: int) -> None:
    """Store *value* under *key* with *ttl* seconds. No-op on error.

    Synchronous — see get_cached for why the previous ``async`` was decorative.
    """
    if _redis_client is None:
        return
    try:
        _redis_client.set(key, value, ex=ttl)
    except Exception as e:
        logger.warning("Redis SET failed (caching skipped): %s", e)
