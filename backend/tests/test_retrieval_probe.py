"""Unit tests for retrieval_probe pure logic: coverage, ranking, recall@k, sources.

The DB/embedder-driven parts (main, run_probe) are exercised manually, not here.
These tests cover the deterministic aggregation that decides whether the gold
rule was retrieved, at what rank, and which sources dominate.
"""
from types import SimpleNamespace

import pytest

from app.rag.provider import LLMProvider
from scripts.retrieval_probe import (
    _NoHydeProvider,
    chunk_covers_refs,
    first_covering_rank,
    fully_covered,
    per_ref_ranks,
    recall_at_k,
    routing_decision,
    source_distribution,
    split_by_route,
    strict_recall_at_k,
)


def _chunk(content: str = "", source_type: str = "rulebook"):
    """Lightweight stand-in for a Chunk: only .content and .source_type matter."""
    return SimpleNamespace(content=content, source_type=source_type)


# ---------------------------------------------------------------------------
# chunk_covers_refs — numeric lineage + errata source matching
# ---------------------------------------------------------------------------

def test_covers_exact_rule_code():
    assert chunk_covers_refs(["103.2"], {"103.2"}, "rulebook") is True


def test_parent_rule_does_not_cover_child_ref():
    # A chunk listing only the parent 103.2 is not evidence the child clause
    # 103.2.b was retrieved — parent coverage was the recall paper hit.
    assert chunk_covers_refs(["103.2.b"], {"103.2"}, "rulebook") is False


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


# ---------------------------------------------------------------------------
# _NoHydeProvider — the probe's zero-quota stand-in must honour the real contract
#
# Why these exist (plan 6.3): the stub used to be a bare class implementing only
# hyde(). The probes are not unit-tested end-to-end (they need a DB), so if the
# retrieval path ever called another provider method, the probe would die of
# AttributeError at runtime — with CI green, at the exact moment you're
# debugging something else and trusting the tool least critically.
#
# Subclassing the LLMProvider ABC moves that failure to construction time, and
# test_stub_can_be_constructed turns it into a CI failure: add a new abstract
# method to LLMProvider and this test breaks immediately, instead of the probe
# breaking silently weeks later.
# ---------------------------------------------------------------------------

def test_stub_is_a_real_provider():
    assert isinstance(_NoHydeProvider(), LLMProvider)


def test_stub_can_be_constructed():
    # Guards the ABC contract: a new abstractmethod on LLMProvider makes this
    # raise TypeError here, in CI, rather than in the probe at 2am.
    _NoHydeProvider()


def test_stub_hyde_returns_empty_so_no_llm_call_happens():
    assert _NoHydeProvider().hyde("anything") == ""


def test_stub_generate_raises_a_named_error_not_attribute_error():
    # If the retrieval path ever reaches generate(), the probe must say WHY —
    # a bare AttributeError would send the next person hunting the wrong bug.
    with pytest.raises(NotImplementedError, match="probe"):
        _NoHydeProvider().generate("q", [])


# ---------------------------------------------------------------------------
# routing_decision — does production replace retrieval with the stuffed rulebook?
#
# Why this exists: without it the probe measures hybrid_search for EVERY
# question, including the ones production never answers from hybrid_search. That
# blind spot produced a false "383-family systemic gap" diagnosis on 2026-07-15
# (4 of the 5 questions route and answer correctly). Mirrors the production
# gate at pipeline.py:690 — routing_enabled AND is_hard_query.
# ---------------------------------------------------------------------------

def test_routing_decision_matches_production_threshold_on_cards():
    # cards >= 2 routes on its own (routing.py::is_hard_query)
    assert routing_decision(card_count=2, keyword_count=0, routing_enabled=True) is True


def test_routing_decision_matches_production_threshold_on_card_plus_keywords():
    # one card needs >= 2 keywords to clear the bar
    assert routing_decision(card_count=1, keyword_count=2, routing_enabled=True) is True


def test_routing_decision_false_below_threshold():
    # eval-020's exact shape: 1 card, 1 keyword -> NOT routed, so its retrieval
    # recall is a real production signal (this is the one live 383 gap).
    assert routing_decision(card_count=1, keyword_count=1, routing_enabled=True) is False


def test_routing_decision_false_when_routing_disabled():
    # flag off -> production uses retrieval for everything, so must the probe
    assert routing_decision(card_count=3, keyword_count=5, routing_enabled=False) is False


# ---------------------------------------------------------------------------
# split_by_route — recall only carries meaning for the non-routed bucket
# ---------------------------------------------------------------------------

def test_split_by_route_separates_buckets():
    results = [
        {"id": "eval-014", "routed": True},
        {"id": "eval-020", "routed": False},
        {"id": "eval-013", "routed": True},
    ]
    routed, retrieved = split_by_route(results)
    assert [r["id"] for r in routed] == ["eval-014", "eval-013"]
    assert [r["id"] for r in retrieved] == ["eval-020"]


def test_split_by_route_empty():
    assert split_by_route([]) == ([], [])


# ---------------------------------------------------------------------------
# per_ref_ranks / strict_recall_at_k — the any-ref masking made visible
#
# Why this exists: chunk_covers_refs (and first_covering_rank through it) score
# a hit when ANY gold ref is covered. That rule is deliberate — for questions
# whose refs are alternatives it's correct — but for questions whose refs are
# conjuncts it hides a real gap. Measured on eval-020 (gold "816, 383.3.d"):
# 816 lands at rank 1 while 383.3.d is absent from the top-15, so the probe
# printed a healthy h=1 for the one question with a genuine 383 gap. Both
# figures are now reported; the gap between them is the size of the lie.
# ---------------------------------------------------------------------------

def test_per_ref_ranks_reports_each_ref_separately():
    chunks = [
        _chunk("816. Attachments do this."),
        _chunk("200. unrelated"),
    ]
    assert per_ref_ranks(["816", "383.3.d"], chunks) == {"816": 1, "383.3.d": None}


def test_per_ref_ranks_empty_refs():
    assert per_ref_ranks([], [_chunk("816. x")]) == {}


def test_per_ref_ranks_finds_each_ref_at_its_own_chunk():
    # One pass must not stop at the first ref it resolves.
    chunks = [
        _chunk("816. Attachments do this."),
        _chunk("200. unrelated"),
        _chunk("383.3.d ordering of triggers."),
    ]
    assert per_ref_ranks(["816", "383.3.d"], chunks) == {"816": 1, "383.3.d": 3}


def test_per_ref_ranks_records_first_covering_chunk_only():
    chunks = [_chunk("816. first"), _chunk("816. second")]
    assert per_ref_ranks(["816"], chunks) == {"816": 1}


def test_strict_recall_requires_every_ref_within_k():
    # eval-020's exact shape: one ref at rank 1, the other absent -> not a
    # strict hit, even though the any-ref recall counts it.
    ranks = [{"816": 1, "383.3.d": None}]
    assert strict_recall_at_k(ranks, 5) == 0.0


def test_strict_recall_counts_when_all_refs_within_k():
    ranks = [{"816": 1, "383.3.d": 4}]
    assert strict_recall_at_k(ranks, 5) == 1.0


def test_strict_recall_excludes_ref_beyond_k():
    ranks = [{"816": 1, "383.3.d": 9}]
    assert strict_recall_at_k(ranks, 5) == 0.0
    assert strict_recall_at_k(ranks, 10) == 1.0


def test_strict_recall_empty_is_zero():
    assert strict_recall_at_k([], 5) == 0.0


def test_strict_and_any_recall_diverge_on_partial_coverage():
    # The headline contrast: any-ref says 100%, strict says 0%. Same data.
    per_ref = [{"816": 1, "383.3.d": None}]
    assert recall_at_k([1], 5) == 1.0
    assert strict_recall_at_k(per_ref, 5) == 0.0


# ---------------------------------------------------------------------------
# fully_covered — the headline: is EVERY gold ref in the generation context?
#
# Third blind spot this closes: the probe used to measure hybrid_search's raw
# output, but production assembles the non-routed context through
# tagged_lookup + _assemble_context + _complete_keyword_families on top of it.
# Measuring the arm and calling it "the context" under-reports — eval-030's
# Deflect family siblings arrive via family completion, which raw hybrid_search
# never shows.
# ---------------------------------------------------------------------------

def test_fully_covered_true_when_every_ref_present():
    assert fully_covered({"816": 1, "383.3.d": 4}) is True


def test_fully_covered_false_when_any_ref_missing():
    assert fully_covered({"816": 1, "383.3.d": None}) is False


def test_fully_covered_empty_is_false():
    # No refs is not evidence of coverage — don't score it as a win.
    assert fully_covered({}) is False


def test_recall_over_retrieved_bucket_ignores_routed_misses():
    # The regression this guards: a routed question whose gold rule is absent
    # from hybrid_search is NOT a production miss — the stuffed rulebook carries
    # it. Folding it into recall is what manufactured the phantom gap.
    results = [
        {"id": "eval-014", "routed": True, "hybrid_rank": None},
        {"id": "eval-020", "routed": False, "hybrid_rank": 3},
    ]
    _, retrieved = split_by_route(results)
    assert recall_at_k([r["hybrid_rank"] for r in retrieved], 5) == 1.0
