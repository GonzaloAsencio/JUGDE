"""Tests for the semantic answer cache (improvement plan 2.3).

The cache reuses the answer of the nearest already-answered question. Its one
dangerous failure is a FALSE POSITIVE — serving the answer to a DIFFERENT
question — so most of these tests pin the guards that prevent it, not the happy
path.

The load-bearing guard is the hard-query exclusion. scripts/semantic_cache_probe.py
measured, on our own eval set:

    eval-013 "... Tideturner DURING MY OPPONENT'S TURN ..."  -> ruling: YES
    eval-014 "... Tideturner ON MY OWN TURN ..."             -> ruling: NO
    cosine: 0.982

Two words apart, opposite answers. No threshold both rejects that pair and still
catches a reworded question (the lowest self-paraphrase cosine is 0.874). The
cache is only safe on the NON-hard subset, where the ceiling collapses to 0.763.
"""
from unittest.mock import MagicMock, patch

from app import semantic_cache
from app.cache import directive_key


# ---------------------------------------------------------------------------
# _semantic_cache_is_safe — the guard the probe forced into existence
# ---------------------------------------------------------------------------

def test_hard_question_is_never_semantically_cacheable():
    """eval-013/eval-014 shape: two cards, cosine 0.982, OPPOSITE rulings."""
    from app.rag.pipeline import _semantic_cache_is_safe

    assert _semantic_cache_is_safe(card_count=2, keyword_count=0) is False


def test_card_plus_two_keywords_is_never_semantically_cacheable():
    from app.rag.pipeline import _semantic_cache_is_safe

    assert _semantic_cache_is_safe(card_count=1, keyword_count=2) is False


def test_plain_rules_question_is_cacheable():
    """"When is damage removed from units?" — no cards, no discriminative
    micro-detail for the embedding to smooth over."""
    from app.rag.pipeline import _semantic_cache_is_safe

    assert _semantic_cache_is_safe(card_count=0, keyword_count=1) is True


# ---------------------------------------------------------------------------
# directive_key — the namespace that keeps a hit from crossing a boundary
# ---------------------------------------------------------------------------

def test_directive_key_is_order_independent():
    assert directive_key(["Vi", "Ahri"]) == directive_key(["Ahri", "Vi"])


def test_directive_key_separates_different_mentions():
    assert directive_key(["Vi"]) != directive_key(["Ahri"])


def test_directive_key_separates_tags_from_mentions():
    """A question tagged @deflect must not match one that merely MENTIONS it."""
    assert directive_key(None, ["deflect"]) != directive_key(["deflect"], None)


def test_directive_key_empty_is_stable():
    assert directive_key(None, None) == directive_key([], [])


# ---------------------------------------------------------------------------
# semantic_cache module — never-raise contract + threshold
# ---------------------------------------------------------------------------

def _pool_returning(row):
    """A pool whose cursor.fetchone() yields *row*."""
    cur = MagicMock()
    cur.fetchone.return_value = row
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    pool = MagicMock()
    pool.getconn.return_value = conn
    return pool, conn


def _lookup(pool, threshold=0.85):
    return semantic_cache.lookup(
        pool, [0.0] * 1024,
        corpus_version="v1", prompt_version="v7",
        directive_key="{}", threshold=threshold, ttl_s=86400,
    )


def test_lookup_returns_match_above_threshold():
    pool, _ = _pool_returning(("key-abc", "the matched question", 0.91))
    with patch("app.semantic_cache.get_conn") as gc:
        gc.return_value.__enter__.return_value = pool.getconn.return_value
        out = _lookup(pool)
    assert out == ("key-abc", "the matched question", 0.91)


def test_lookup_rejects_below_threshold():
    """0.84 vs a 0.85 floor — the near-miss must NOT be served."""
    pool, _ = _pool_returning(("key-abc", "a different question", 0.84))
    with patch("app.semantic_cache.get_conn") as gc:
        gc.return_value.__enter__.return_value = pool.getconn.return_value
        assert _lookup(pool) is None


def test_lookup_returns_none_on_empty_table():
    pool, _ = _pool_returning(None)
    with patch("app.semantic_cache.get_conn") as gc:
        gc.return_value.__enter__.return_value = pool.getconn.return_value
        assert _lookup(pool) is None


def test_lookup_never_raises_on_db_error():
    """A cache is an optimization — a DB failure degrades to a miss, never a 500."""
    with patch("app.semantic_cache.get_conn", side_effect=RuntimeError("db down")):
        assert _lookup(MagicMock()) is None


def test_remember_never_raises_on_db_error():
    with patch("app.semantic_cache.get_conn", side_effect=RuntimeError("db down")):
        semantic_cache.remember(
            MagicMock(), "q", [0.0] * 1024, "key",
            corpus_version="v1", prompt_version="v7", directive_key="{}",
        )  # must not raise


def test_remember_commits():
    pool, conn = _pool_returning(None)
    with patch("app.semantic_cache.get_conn") as gc:
        gc.return_value.__enter__.return_value = conn
        semantic_cache.remember(
            pool, "q", [0.0] * 1024, "key",
            corpus_version="v1", prompt_version="v7", directive_key="{}",
        )
    conn.commit.assert_called_once()


def test_forget_never_raises_on_db_error():
    with patch("app.semantic_cache.get_conn", side_effect=RuntimeError("db down")):
        semantic_cache.forget(MagicMock(), "key")  # must not raise


# ---------------------------------------------------------------------------
# Pipeline wiring
# ---------------------------------------------------------------------------

def _settings(enabled: bool):
    from tests.test_pipeline import _fake_settings

    s = _fake_settings()
    s.semantic_cache_enabled = enabled
    s.semantic_cache_threshold = 0.85
    s.hard_query_routing = False
    return s


def _entities(card_tags=(), ambiguous=0):
    from app.rag.pipeline import _Entities

    return _Entities(auto_card_tags=list(card_tags), ambiguous_champion_count=ambiguous)


def _run(settings, entities, *, lookup_result=None, redis_on=True, cached_raw=None):
    """Drive answer_question with retrieval stubbed out; return the semantic_cache mock.

    *cached_raw* is what Redis returns for the NEIGHBOUR's key on a semantic hit
    (None = the pointer is stale).
    """
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    from app.rag.pipeline import answer_question

    sem = MagicMock()
    sem.lookup.return_value = lookup_result
    with (
        patch("app.rag.pipeline.semantic_cache", sem),
        patch("app.rag.pipeline.cache_is_enabled", return_value=redis_on),
        patch("app.rag.pipeline._detect_entities", return_value=entities),
        patch("app.rag.pipeline.hybrid_search", return_value=[]),
        patch("app.rag.pipeline.tagged_lookup", return_value=[]),
        # The exact-key GET must miss (that's the precondition for a semantic
        # lookup); the neighbour-key GET returns cached_raw. Both go through
        # get_cached, and the exact one is always first.
        patch("app.rag.pipeline.get_cached", side_effect=[None, cached_raw]),
        patch("app.rag.pipeline.set_cached"),
    ):
        result = answer_question(
            "When is damage removed from units?",
            FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings,
        )
    return sem, result


def test_flag_off_never_touches_the_semantic_cache():
    """Byte-identical to pre-2.3 behaviour: no lookup, no remember."""
    sem, _ = _run(_settings(enabled=False), _entities())
    sem.lookup.assert_not_called()
    sem.remember.assert_not_called()


def test_no_redis_never_touches_the_semantic_cache():
    """The ANSWER lives in Redis — with no Redis a hit could only point at
    nothing, so the ANN query would be pure waste. This is also what keeps
    scripts/eval.py (which never calls init_redis) byte-identical."""
    sem, _ = _run(_settings(enabled=True), _entities(), redis_on=False)
    sem.lookup.assert_not_called()
    sem.remember.assert_not_called()


def test_hard_question_is_neither_looked_up_nor_remembered():
    """The eval-013/eval-014 guard, enforced at the pipeline boundary: a hard
    question must not even be REMEMBERED, or it becomes the wrong-answer
    neighbour for the next paraphrase."""
    sem, _ = _run(_settings(enabled=True), _entities(card_tags=["vex apathetic", "tideturner"]))
    sem.lookup.assert_not_called()
    sem.remember.assert_not_called()


def test_semantic_hit_returns_the_neighbours_answer():
    cached = '{"answer": "Damage heals at end of turn.", "citations": [], "confidence": 0.9}'
    sem, result = _run(
        _settings(enabled=True), _entities(),
        lookup_result=("neighbour-key", "when does damage heal?", 0.93),
        cached_raw=cached,
    )
    assert result.cache_hit is True
    assert result.answer == "Damage heals at end of turn."
    # The neighbour's answer was resolved by its OWN key, not the exact one.
    assert sem.lookup.call_count == 1


def test_stale_pointer_is_forgotten_and_falls_through():
    """Redis evicted the answer early: drop the dangling row instead of letting
    it shadow a real neighbour, and regenerate."""
    sem, result = _run(
        _settings(enabled=True), _entities(),
        lookup_result=("dead-key", "an expired question", 0.93),
    )
    assert sem.forget.call_count == 1
    assert sem.forget.call_args[0][1] == "dead-key"
    assert result.cache_hit is False
