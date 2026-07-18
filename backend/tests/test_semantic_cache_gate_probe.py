"""Unit tests for the pure logic of scripts/semantic_cache_gate_probe.py.

Same contract as test_hyde_skip_probe: the harness runs are manual, but the
verdict — the pre-committed rule from plan §2.3 — is pinned by CI so it cannot
drift into a friendlier reading after the numbers are in.
"""
from scripts.semantic_cache_gate_probe import (
    CrossMatch,
    ParaphraseResult,
    gate_verdict,
)


def _hit(original="q1"):
    return ParaphraseResult(
        original=original, paraphrase="reworded",
        matched_question=original, similarity=0.9, sentinel_ok=True,
    )


def _cross():
    return CrossMatch(question="a", matched_question="b", similarity=0.86)


# --- ParaphraseResult.ok ---------------------------------------------------

def test_hit_on_own_original_with_sentinel_is_ok():
    assert _hit().ok


def test_no_match_is_not_ok():
    p = ParaphraseResult("q1", "reworded", None, None, False)
    assert not p.ok


def test_wrong_question_match_is_not_ok():
    # Matching >= threshold but to ANOTHER question is the dangerous failure,
    # not a partial success.
    p = ParaphraseResult("q1", "reworded", "q2", 0.95, sentinel_ok=True)
    assert not p.ok


def test_right_match_with_wrong_sentinel_is_not_ok():
    # The ANN matched but Redis resolved the wrong/no answer: the round-trip
    # is the claim, not the ANN alone.
    p = ParaphraseResult("q1", "reworded", "q1", 0.95, sentinel_ok=False)
    assert not p.ok


# --- gate_verdict ----------------------------------------------------------

def test_all_hits_no_cross_isolated_is_alive():
    assert gate_verdict([_hit(), _hit("q2")], [], True) == "ALIVE"


def test_any_paraphrase_failure_kills():
    failed = ParaphraseResult("q1", "reworded", None, None, False)
    assert gate_verdict([_hit(), failed], [], True) == "DEAD"


def test_broken_isolation_kills():
    assert gate_verdict([_hit()], [], False) == "DEAD"


def test_cross_matches_force_human_read_never_silent_alive():
    assert gate_verdict([_hit()], [_cross()], True) == "NEEDS_HUMAN_READ"


def test_empty_paraphrase_list_is_a_broken_run_not_a_pass():
    assert gate_verdict([], [], True) == "DEAD"
