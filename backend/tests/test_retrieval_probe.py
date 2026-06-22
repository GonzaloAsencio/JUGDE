"""Unit tests for retrieval_probe pure logic: coverage, ranking, recall@k, sources.

The DB/embedder-driven parts (main, run_probe) are exercised manually, not here.
These tests cover the deterministic aggregation that decides whether the gold
rule was retrieved, at what rank, and which sources dominate.
"""
from types import SimpleNamespace

from scripts.retrieval_probe import (
    chunk_covers_refs,
    first_covering_rank,
    recall_at_k,
    source_distribution,
)


def _chunk(content: str = "", source_type: str = "rulebook"):
    """Lightweight stand-in for a Chunk: only .content and .source_type matter."""
    return SimpleNamespace(content=content, source_type=source_type)


# ---------------------------------------------------------------------------
# chunk_covers_refs — numeric lineage + errata source matching
# ---------------------------------------------------------------------------

def test_covers_exact_rule_code():
    assert chunk_covers_refs(["103.2"], {"103.2"}, "rulebook") is True


def test_covers_when_chunk_lists_parent_rule():
    # ref 103.2.b is covered by a chunk that lists the parent 103.2
    assert chunk_covers_refs(["103.2.b"], {"103.2"}, "rulebook") is True


def test_covers_when_chunk_lists_child_rule():
    # ref 103 is covered by a chunk that lists a child 103.2
    assert chunk_covers_refs(["103"], {"103.2"}, "rulebook") is True


def test_does_not_cover_unrelated_code():
    assert chunk_covers_refs(["103.2"], {"104"}, "rulebook") is False


def test_errata_ref_covered_only_by_errata_source():
    ref = ["errata/origins/dark-child-starter"]
    assert chunk_covers_refs(ref, set(), "errata") is True
    assert chunk_covers_refs(ref, set(), "rulebook") is False


def test_multi_ref_covered_when_any_ref_hits():
    # comma-separated refs already split upstream; covered if ANY matches
    assert chunk_covers_refs(["383.3.d.1", "459.2.d"], {"459.2.d"}, "rulebook") is True


# ---------------------------------------------------------------------------
# first_covering_rank — 1-based rank of the first chunk covering the gold ref
# ---------------------------------------------------------------------------

def test_first_covering_rank_returns_one_based_position():
    chunks = [
        _chunk("200. something else"),
        _chunk("143. Units enter exhausted. 143.4 details here."),
        _chunk("300. other"),
    ]
    assert first_covering_rank(["143.4"], chunks) == 2


def test_first_covering_rank_returns_none_when_absent():
    chunks = [_chunk("200. x"), _chunk("300. y")]
    assert first_covering_rank(["143.4"], chunks) is None


def test_first_covering_rank_uses_errata_source():
    chunks = [
        _chunk("103. rulebook text", source_type="rulebook"),
        _chunk("correction text", source_type="errata"),
    ]
    assert first_covering_rank(["errata/foo/bar"], chunks) == 2


# ---------------------------------------------------------------------------
# recall_at_k — fraction of questions whose gold landed within rank k
# ---------------------------------------------------------------------------

def test_recall_at_k_counts_only_within_k():
    ranks = [1, 6, None, 3]  # within 5: ranks 1 and 3 -> 2/4
    assert recall_at_k(ranks, 5) == 0.5


def test_recall_at_k_none_is_a_miss():
    assert recall_at_k([None, None], 15) == 0.0


def test_recall_at_k_empty_is_zero():
    assert recall_at_k([], 5) == 0.0


def test_recall_at_15_includes_ranks_above_5():
    ranks = [1, 6, 12, None]  # within 15: 1, 6, 12 -> 3/4
    assert recall_at_k(ranks, 15) == 0.75


# ---------------------------------------------------------------------------
# source_distribution — which source types dominate a result slice
# ---------------------------------------------------------------------------

def test_source_distribution_counts_by_type():
    assert source_distribution(["rulebook", "rulebook", "faq"]) == {
        "rulebook": 2,
        "faq": 1,
    }


def test_source_distribution_empty():
    assert source_distribution([]) == {}
