"""Unit tests for backend/app/cache.py."""
from unittest.mock import MagicMock, patch

from app.cache import get_cached, make_cache_key, set_cached


# ---------------------------------------------------------------------------
# make_cache_key
# ---------------------------------------------------------------------------

def test_make_cache_key_normalizes_case():
    key1 = make_cache_key("Who is Zara?", "v1")
    key2 = make_cache_key("WHO IS ZARA?", "v1")
    assert key1 == key2


def test_make_cache_key_strips_whitespace():
    key1 = make_cache_key("  who is zara?  ", "v1")
    key2 = make_cache_key("who is zara?", "v1")
    assert key1 == key2


def test_make_cache_key_differs_by_corpus_version():
    key1 = make_cache_key("who is zara?", "v1")
    key2 = make_cache_key("who is zara?", "v2")
    assert key1 != key2


def test_make_cache_key_differs_by_question():
    key1 = make_cache_key("who is zara?", "v1")
    key2 = make_cache_key("what is zara?", "v1")
    assert key1 != key2


def test_make_cache_key_differs_by_card_mentions():
    key1 = make_cache_key("who is zara?", "v1", ["CardA"])
    key2 = make_cache_key("who is zara?", "v1", ["CardB"])
    assert key1 != key2


def test_make_cache_key_card_mentions_sorted():
    """Order of card_mentions must not affect the key."""
    key1 = make_cache_key("who is zara?", "v1", ["CardA", "CardB"])
    key2 = make_cache_key("who is zara?", "v1", ["CardB", "CardA"])
    assert key1 == key2


def test_make_cache_key_empty_mentions_equals_none():
    """Explicitly empty list and None should produce the same key."""
    key1 = make_cache_key("who is zara?", "v1", [])
    key2 = make_cache_key("who is zara?", "v1", None)
    assert key1 == key2


def test_make_cache_key_mentions_differ_from_no_mentions():
    key1 = make_cache_key("who is zara?", "v1", ["CardA"])
    key2 = make_cache_key("who is zara?", "v1")
    assert key1 != key2


def test_make_cache_key_is_hex_string():
    key = make_cache_key("test question", "v1")
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)


# ---------------------------------------------------------------------------
# get_cached — graceful degradation when Redis raises
# ---------------------------------------------------------------------------

def test_get_cached_returns_none_when_redis_raises():
    mock_redis = MagicMock()
    mock_redis.get.side_effect = RuntimeError("connection refused")

    with patch("app.cache._redis_client", mock_redis):
        result = get_cached("any-key")

    assert result is None


def test_get_cached_returns_none_when_no_client():
    with patch("app.cache._redis_client", None):
        result = get_cached("any-key")

    assert result is None


def test_get_cached_returns_value_on_hit():
    mock_redis = MagicMock()
    mock_redis.get.return_value = '{"answer": "test"}'

    with patch("app.cache._redis_client", mock_redis):
        result = get_cached("existing-key")

    assert result == '{"answer": "test"}'


# ---------------------------------------------------------------------------
# set_cached — graceful degradation when Redis raises
# ---------------------------------------------------------------------------

def test_set_cached_is_noop_when_redis_raises():
    mock_redis = MagicMock()
    mock_redis.set.side_effect = RuntimeError("connection refused")

    with patch("app.cache._redis_client", mock_redis):
        # Must not raise
        set_cached("key", "value", ttl=60)


def test_set_cached_is_noop_when_no_client():
    with patch("app.cache._redis_client", None):
        # Must not raise
        set_cached("key", "value", ttl=60)
