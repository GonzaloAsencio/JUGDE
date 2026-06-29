"""Unit tests for retrieval: _rrf_fuse (pure), fts_search, hybrid_search."""
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from app.rag.retrieval import Chunk, _dedup_card_printings, _printing_key, _rrf_fuse, fuse_results

_RRF_K = 60


def _card(id: str, name: str, similarity: float = 0.6) -> Chunk:
    """A card chunk whose content carries a **Name** field (printing variant)."""
    return Chunk(
        id=id,
        content=f"## {name} **Name**: {name} **Set**: SomeSet **Text**: rules text here.",
        section=name,
        parent_section=None,
        source_type="card",
        similarity=similarity,
    )


# ---------------------------------------------------------------------------
# _printing_key / _dedup_card_printings (pure)
# ---------------------------------------------------------------------------

def test_printing_key_strips_variant_suffix():
    base = _card("1", "Irelia - Blade Dancer")
    metal = _card("2", "Irelia - Blade Dancer (Metal)")
    assert _printing_key(base) == _printing_key(metal) == "irelia - blade dancer"


def test_printing_key_none_for_non_card():
    chunk = Chunk("r1", "**Name**: Foo", "Sec", None, "rulebook", 0.5)
    assert _printing_key(chunk) is None


def test_printing_key_none_when_no_name_field():
    chunk = Chunk("c1", "no name field here", "Sec", None, "card", 0.5)
    assert _printing_key(chunk) is None


def test_dedup_keeps_first_printing_drops_rest():
    chunks = [
        _card("1", "Irelia - Blade Dancer", 0.65),
        _card("2", "Irelia - Blade Dancer (Overnumbered)", 0.63),
        _card("3", "Irelia - Blade Dancer (Metal)", 0.62),
    ]
    out = _dedup_card_printings(chunks)
    assert [c.id for c in out] == ["1"]


def test_dedup_preserves_order_and_distinct_cards():
    chunks = [
        _card("1", "Sunken Temple"),
        _card("2", "Irelia - Blade Dancer"),
        _card("3", "Irelia - Blade Dancer (Metal)"),
        _card("4", "Red Brambleback"),
    ]
    out = _dedup_card_printings(chunks)
    assert [c.id for c in out] == ["1", "2", "4"]


def test_dedup_passes_through_non_cards_and_unparseable():
    rule = Chunk("r1", "rule text", "Sec", None, "rulebook", 0.5)
    bad = Chunk("c9", "card with no name", "Sec", None, "card", 0.5)
    chunks = [rule, bad, _card("1", "Foo"), _card("2", "Foo")]
    out = _dedup_card_printings(chunks)
    assert [c.id for c in out] == ["r1", "c9", "1"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunk(id: str = "c1", similarity: float = 0.9, source_type: str = "rulebook") -> Chunk:
    return Chunk(
        id=id,
        content="Some content.",
        section="Section",
        parent_section=None,
        source_type=source_type,
        similarity=similarity,
    )


def _make_conn_ctx(rows):
    """Return (fake_get_conn, cursor_mock) for monkeypatching get_conn."""
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    @contextmanager
    def fake_get_conn(_pool):
        yield conn

    return fake_get_conn, cur


# ---------------------------------------------------------------------------
# _rrf_fuse tests (pure, no mocks)
# ---------------------------------------------------------------------------

def test_rrf_chunk_only_in_vector_uses_single_score():
    result = _rrf_fuse([_chunk("a")], [], rrf_k=_RRF_K, top_k=10)
    assert len(result) == 1
    assert result[0].id == "a"


def test_rrf_chunk_in_both_sums_scores():
    result = _rrf_fuse([_chunk("a", 0.9)], [_chunk("a", 0.0)], rrf_k=_RRF_K, top_k=10)
    assert len(result) == 1
    assert result[0].id == "a"


def test_rrf_dedup_by_id():
    result = _rrf_fuse([_chunk("a")], [_chunk("a", 0.0)], rrf_k=_RRF_K, top_k=10)
    assert [c.id for c in result].count("a") == 1


def test_rrf_orders_by_score_desc():
    # "a" in both lists (rank 1 each) → score 2/61; "b" only in vector (rank 2) → 1/62
    result = _rrf_fuse(
        [_chunk("a"), _chunk("b")],
        [_chunk("a", 0.0)],
        rrf_k=_RRF_K,
        top_k=10,
    )
    assert result[0].id == "a"


def test_rrf_tie_break_favors_vector():
    # "v" at rank 1 vector-only; "f" at rank 1 fts-only → tie (same score), vector wins
    result = _rrf_fuse([_chunk("v")], [_chunk("f", 0.0)], rrf_k=_RRF_K, top_k=10)
    assert result[0].id == "v"


def test_rrf_truncates_to_top_k():
    chunks = [_chunk(str(i)) for i in range(5)]
    result = _rrf_fuse(chunks, [], rrf_k=_RRF_K, top_k=3)
    assert len(result) == 3


def test_rrf_empty_vector_returns_fts_ordering():
    result = _rrf_fuse([], [_chunk("a", 0.0), _chunk("b", 0.0)], rrf_k=_RRF_K, top_k=10)
    assert result[0].id == "a"
    assert result[1].id == "b"


def test_rrf_empty_fts_returns_vector_ordering():
    result = _rrf_fuse([_chunk("a"), _chunk("b", 0.5)], [], rrf_k=_RRF_K, top_k=10)
    assert result[0].id == "a"
    assert result[1].id == "b"


def test_rrf_both_empty_returns_empty():
    assert _rrf_fuse([], [], rrf_k=_RRF_K, top_k=10) == []


def test_rrf_preserves_similarity_from_vector_side():
    # same id in both lists; similarity must come from vector chunk (0.95), not FTS (0.0)
    result = _rrf_fuse([_chunk("a", 0.95)], [_chunk("a", 0.0)], rrf_k=_RRF_K, top_k=10)
    assert result[0].similarity == 0.95


# ---------------------------------------------------------------------------
# Authority chain: errata > patch_notes > rulebook
#
# An errata exists to CORRECT the base rule; when they conflict the errata
# supersedes the rule — always. Retrieval must surface authoritative sources
# above the base rule, never below it.
#
# Each test mirrors the two source chunks across vector/fts at swapped ranks,
# so their base RRF scores are identical and ONLY the authority boost decides.
# ---------------------------------------------------------------------------

def test_rrf_errata_outranks_rulebook_on_equal_base_score():
    errata = _chunk("e", source_type="errata")
    rulebook = _chunk("r", source_type="rulebook")
    result = _rrf_fuse(
        [errata, rulebook],   # vector: errata rank1, rulebook rank2
        [rulebook, errata],   # fts:    rulebook rank1, errata rank2
        rrf_k=_RRF_K,
        top_k=10,
    )
    assert result[0].id == "e", "errata must supersede the base rule"


def test_rrf_patch_notes_outranks_rulebook_on_equal_base_score():
    patch = _chunk("p", source_type="patch_notes")
    rulebook = _chunk("r", source_type="rulebook")
    result = _rrf_fuse(
        [patch, rulebook],
        [rulebook, patch],
        rrf_k=_RRF_K,
        top_k=10,
    )
    assert result[0].id == "p", "patch_notes must outrank the base rule"


def test_rrf_errata_outranks_patch_notes_on_equal_base_score():
    errata = _chunk("e", source_type="errata")
    patch = _chunk("p", source_type="patch_notes")
    result = _rrf_fuse(
        [errata, patch],
        [patch, errata],
        rrf_k=_RRF_K,
        top_k=10,
    )
    assert result[0].id == "e", "errata must outrank patch_notes"


def test_rrf_authority_order_errata_patch_rulebook():
    errata = _chunk("e", source_type="errata")
    patch = _chunk("p", source_type="patch_notes")
    rulebook = _chunk("r", source_type="rulebook")
    # all three at identical mirrored ranks → equal base score, authority decides
    result = _rrf_fuse(
        [errata, patch, rulebook],
        [rulebook, patch, errata],
        rrf_k=_RRF_K,
        top_k=10,
    )
    assert [c.id for c in result] == ["e", "p", "r"]


def test_authority_boost_mild_keeps_clearly_better_rulebook_on_top():
    # Regression guard for the sim_102 tuning. A rulebook chunk clearly ahead on
    # real retrieval (vector rank 1) must NOT be buried below an errata chunk four
    # ranks behind (rank 5). A strong boost flips them — errata 1.10/(60+5)=0.01692
    # beats rulebook 1.0/(60+1)=0.01639 — pushing rulebook gold past the top-5
    # cutoff, which cost 6pp recall@5 on the eval probe (53% vs 59%). The mild
    # boost keeps the clearly-better rulebook on top while errata still wins on
    # comparable ranks (the tests above). FTS is dormant, so the second list is empty.
    rulebook = _chunk("r", source_type="rulebook")
    fillers = [_chunk(f"f{i}", source_type="rulebook") for i in range(3)]
    errata = _chunk("e", source_type="errata")
    result = _rrf_fuse([rulebook, *fillers, errata], [], rrf_k=_RRF_K, top_k=10)
    assert result[0].id == "r", "a clearly-better rulebook chunk must not be buried by a mild errata boost"


# ---------------------------------------------------------------------------
# fuse_results: public two-arm fusion for the raw + HyDE strategy (fuse_eq).
#
# This is the production surface of the experiment's winner: RRF-fuse two FULL
# hybrid_search result lists (raw question arm + HyDE arm) with equal weight.
# It must behave like _rrf_fuse but with honest "primary/secondary" semantics:
# the primary (raw) arm wins ties so a question that already retrieves well is
# never displaced by the HyDE arm (protects eval-010: stays rank 1).
# ---------------------------------------------------------------------------

def test_fuse_results_combines_both_arms():
    result = fuse_results([_chunk("a")], [_chunk("b", 0.0)], rrf_k=_RRF_K, top_k=10)
    assert {c.id for c in result} == {"a", "b"}


def test_fuse_results_tie_break_favors_primary_arm():
    # identical rank in each arm → tie; primary (raw) arm must win position
    result = fuse_results([_chunk("p")], [_chunk("s", 0.0)], rrf_k=_RRF_K, top_k=10)
    assert result[0].id == "p"


def test_fuse_results_same_chunk_sums_score_and_keeps_primary_object():
    # a chunk retrieved by both arms must dedup to one, summing scores, and keep
    # the primary-side similarity (a real cosine), not the secondary one
    result = fuse_results([_chunk("x", 0.95)], [_chunk("x", 0.40)], rrf_k=_RRF_K, top_k=10)
    assert len(result) == 1
    assert result[0].similarity == 0.95


def test_fuse_results_empty_secondary_returns_primary_ordering():
    result = fuse_results([_chunk("a"), _chunk("b", 0.5)], [], rrf_k=_RRF_K, top_k=10)
    assert [c.id for c in result] == ["a", "b"]


def test_fuse_results_truncates_to_top_k():
    arm_a = [_chunk(str(i)) for i in range(5)]
    assert len(fuse_results(arm_a, [], rrf_k=_RRF_K, top_k=3)) == 3


def test_fuse_results_authority_boost_applies_across_arms():
    # equal mirrored ranks → base scores equal; errata must still outrank rulebook
    errata = _chunk("e", source_type="errata")
    rulebook = _chunk("r", source_type="rulebook")
    result = fuse_results([errata, rulebook], [rulebook, errata], rrf_k=_RRF_K, top_k=10)
    assert result[0].id == "e"


# ---------------------------------------------------------------------------
# fts_search tests (monkeypatch get_conn)
# ---------------------------------------------------------------------------

def test_fts_search_returns_chunks(monkeypatch):
    rows = [("id1", "content one", "Section A", None, "rulebook", None)]
    fake_conn, _ = _make_conn_ctx(rows)
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import fts_search
    result = fts_search(MagicMock(), "double tap", "v1", top_k=5)

    assert len(result) == 1
    assert result[0].id == "id1"
    assert result[0].similarity == 0.0


def test_fts_search_empty_results_returns_empty_list(monkeypatch):
    fake_conn, _ = _make_conn_ctx([])
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import fts_search
    assert fts_search(MagicMock(), "nothing matches", "v1") == []


def test_fts_search_passes_correct_sql_params(monkeypatch):
    fake_conn, cur = _make_conn_ctx([])
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import fts_search
    fts_search(MagicMock(), "test query", "v2", top_k=7)

    args = cur.execute.call_args[0][1]
    assert args == ("v2", "test query", "test query", 7)


def test_fts_search_uses_simple_dictionary():
    from app.rag import retrieval
    assert "'simple'" in retrieval._FTS_SQL
    assert "'english'" not in retrieval._FTS_SQL


# ---------------------------------------------------------------------------
# hybrid_search tests (monkeypatch vector_search and fts_search)
# ---------------------------------------------------------------------------

# NOTE: the FTS arm is DORMANT. A deterministic probe measured vector-only @5
# recall (47%) ABOVE vector+FTS (41%): plainto_tsquery over a full NL question
# rarely matches rule text and only dilutes the RRF. hybrid_search therefore
# returns vector results (with authority boost preserved) and does NOT query or
# fuse FTS. fts_search/_FTS_SQL stay for future re-evaluation.

def test_hybrid_search_returns_vector_only_fts_dormant(monkeypatch):
    chunk_v, chunk_f = _chunk("v1"), _chunk("f1", 0.0)
    monkeypatch.setattr("app.rag.retrieval.vector_search", lambda *a, **kw: [chunk_v])
    monkeypatch.setattr("app.rag.retrieval.fts_search", lambda *a, **kw: [chunk_f])

    from app.rag.retrieval import hybrid_search
    result = hybrid_search(MagicMock(), [], "test", "v1", top_k=5)

    ids = {c.id for c in result}
    assert "v1" in ids
    assert "f1" not in ids, "fts-only chunks must not appear while FTS is dormant"


def test_hybrid_search_fetches_vector_at_top_k_fetch_and_skips_fts(monkeypatch):
    vec_calls, fts_calls = [], []

    def fake_vector(pool, emb, corpus_version, top_k, set_filter=None):
        vec_calls.append(top_k)
        return []

    def fake_fts(pool, query_text, corpus_version, top_k, set_filter=None):
        fts_calls.append(top_k)
        return []

    monkeypatch.setattr("app.rag.retrieval.vector_search", fake_vector)
    monkeypatch.setattr("app.rag.retrieval.fts_search", fake_fts)

    from app.rag.retrieval import hybrid_search
    hybrid_search(MagicMock(), [], "q", "v1", top_k=5, top_k_fetch=20)

    assert vec_calls == [20]
    assert fts_calls == [], "FTS must not be queried while dormant"


def test_hybrid_search_preserves_authority_boost(monkeypatch):
    # Dropping FTS must NOT drop the authority chain: errata still supersedes the
    # base rule even when vector returns it at a lower raw rank.
    errata = _chunk("e", source_type="errata")
    rulebook = _chunk("r", source_type="rulebook")
    monkeypatch.setattr("app.rag.retrieval.vector_search", lambda *a, **kw: [rulebook, errata])
    monkeypatch.setattr("app.rag.retrieval.fts_search", lambda *a, **kw: [])

    from app.rag.retrieval import hybrid_search
    result = hybrid_search(MagicMock(), [], "q", "v1", top_k=5)

    assert result[0].id == "e", "errata must outrank the base rule (authority preserved)"


def test_hybrid_search_returns_top_k_only(monkeypatch):
    chunks = [_chunk(str(i)) for i in range(10)]
    monkeypatch.setattr("app.rag.retrieval.vector_search", lambda *a, **kw: chunks)
    monkeypatch.setattr("app.rag.retrieval.fts_search", lambda *a, **kw: [])

    from app.rag.retrieval import hybrid_search
    assert len(hybrid_search(MagicMock(), [], "q", "v1", top_k=3)) == 3


def test_hybrid_search_fts_empty_returns_vector_ordering(monkeypatch):
    chunk_a, chunk_b = _chunk("a"), _chunk("b", 0.5)
    monkeypatch.setattr("app.rag.retrieval.vector_search", lambda *a, **kw: [chunk_a, chunk_b])
    monkeypatch.setattr("app.rag.retrieval.fts_search", lambda *a, **kw: [])

    from app.rag.retrieval import hybrid_search
    result = hybrid_search(MagicMock(), [], "q", "v1", top_k=5)

    assert result[0].id == "a" and result[1].id == "b"


def test_hybrid_search_vector_empty_returns_empty_fts_dormant(monkeypatch):
    # With FTS dormant, an empty vector result yields no chunks — FTS does not
    # backfill (it used to via the fusion, but that path is gone).
    chunk_a, chunk_b = _chunk("a", 0.0), _chunk("b", 0.0)
    monkeypatch.setattr("app.rag.retrieval.vector_search", lambda *a, **kw: [])
    monkeypatch.setattr("app.rag.retrieval.fts_search", lambda *a, **kw: [chunk_a, chunk_b])

    from app.rag.retrieval import hybrid_search
    assert hybrid_search(MagicMock(), [], "q", "v1", top_k=5) == []


def test_hybrid_search_both_empty_returns_empty(monkeypatch):
    monkeypatch.setattr("app.rag.retrieval.vector_search", lambda *a, **kw: [])
    monkeypatch.setattr("app.rag.retrieval.fts_search", lambda *a, **kw: [])

    from app.rag.retrieval import hybrid_search
    assert hybrid_search(MagicMock(), [], "q", "v1") == []


# ---------------------------------------------------------------------------
# tagged_lookup tests
# ---------------------------------------------------------------------------

def test_tagged_lookup_empty_tags_returns_empty():
    from app.rag.retrieval import tagged_lookup
    assert tagged_lookup(MagicMock(), [], "v1") == []


def test_tagged_lookup_returns_chunk_with_zero_similarity(monkeypatch):
    """Tagged lookup is a lexical section match — it computes no cosine, so it
    must NOT fabricate a 1.0 similarity that would inflate downstream confidence."""
    rows = [("id1", "content", "Accelerate", None, "rulebook", None)]
    fake_conn, _ = _make_conn_ctx(rows)
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import tagged_lookup
    result = tagged_lookup(MagicMock(), ["accelerate"], "v1")

    assert len(result) == 1
    assert result[0].id == "id1"
    assert result[0].similarity == 0.0


def test_tagged_lookup_deduplicates_same_chunk_across_tags(monkeypatch):
    rows = [("id1", "content", "Accelerate", None, "rulebook", None)]
    fake_conn, _ = _make_conn_ctx(rows)
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import tagged_lookup
    result = tagged_lookup(MagicMock(), ["accelerate", "accel"], "v1")
    assert [c.id for c in result].count("id1") == 1


def test_tagged_sql_prioritizes_cards_above_rulebook():
    """Ordering must surface card chunks before rulebook chunks when both share a section."""
    from app.rag import retrieval
    sql = retrieval._TAGGED_SQL
    card_clause = sql.find("source_type = 'card'")
    rulebook_clause = sql.find("source_type = 'rulebook'")
    assert card_clause != -1, "card clause must be present in _TAGGED_SQL"
    assert rulebook_clause != -1, "rulebook fallback must remain in _TAGGED_SQL"
    assert card_clause < rulebook_clause, "card clause must come first in the ORDER BY"


def test_tagged_lookup_returns_card_chunk_when_tag_matches_card_section(monkeypatch):
    """Sanity: a card-section match returns a chunk with source_type='card'."""
    rows = [("yasuo-id", "## Yasuo ...", "Yasuo", None, "card", None)]
    fake_conn, _ = _make_conn_ctx(rows)
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import tagged_lookup
    result = tagged_lookup(MagicMock(), ["yasuo"], "v1")
    assert len(result) == 1
    assert result[0].source_type == "card"
    assert result[0].similarity == 0.0


def test_tagged_lookup_multiple_tags_merges_distinct_chunks(monkeypatch):
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.side_effect = [
        [("id1", "c1", "Accelerate", None, "rulebook", None)],
        [("id2", "c2", "Action", None, "rulebook", None)],
    ]
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    @contextmanager
    def fake_conn(_pool):
        yield conn

    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import tagged_lookup
    result = tagged_lookup(MagicMock(), ["accelerate", "action"], "v1")
    assert {c.id for c in result} == {"id1", "id2"}
