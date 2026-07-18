"""Unit tests for the pure logic of scripts/hyde_skip_probe.py.

The DB-driven measurement is a manual run; what CI pins is the verdict logic —
the pre-committed rule (plan §2.1) applied to measured rows must not drift into
a friendlier reading after the fact.
"""
from scripts.hyde_skip_probe import (
    CONFIDENCE_DROP_REVIEW,
    GateRow,
    confidence_review,
    gate_verdict,
)


def _row(qid="q", predicted=False, actual=False, stuffing_unavailable=False):
    return GateRow(
        id=qid, predicted=predicted, actual=actual,
        stuffing_unavailable=stuffing_unavailable,
    )


# --- GateRow.kind ----------------------------------------------------------

def test_agreement_in_both_directions_is_agree():
    assert _row(predicted=True, actual=True).kind == "agree"
    assert _row(predicted=False, actual=False).kind == "agree"


def test_false_positive_is_predicted_without_actual():
    # The dangerous direction: the skipped HyDE arm belonged to a query that
    # keeps its retrieval.
    assert _row(predicted=True, actual=False).kind == "false_positive"


def test_false_negative_is_actual_without_prediction():
    assert _row(predicted=False, actual=True).kind == "false_negative"


def test_stuffing_unavailable_outranks_false_positive():
    # Gate said route, stuffing failed: the documented broken-deploy degrade,
    # not a prediction defect — must not be counted as a flag-killing mismatch.
    row = _row(predicted=True, actual=False, stuffing_unavailable=True)
    assert row.kind == "stuffing_unavailable"


# --- gate_verdict ----------------------------------------------------------

def test_all_agree_with_savings_is_alive():
    rows = [_row("a", predicted=True, actual=True), _row("b")]
    result = gate_verdict(rows)
    assert result["verdict"] == "ALIVE"
    assert result["savings"] == 1
    assert result["mismatches"] == []


def test_any_mismatch_kills():
    rows = [_row("a", predicted=True, actual=True), _row("b", predicted=True)]
    assert gate_verdict(rows)["verdict"] == "DEAD"


def test_zero_savings_kills_even_with_full_agreement():
    # A no-op feature is dead code with a config surface (claim 2).
    rows = [_row("a"), _row("b")]
    assert gate_verdict(rows)["verdict"] == "DEAD"


def test_stuffing_unavailable_does_not_kill_but_is_reported():
    rows = [
        _row("a", predicted=True, actual=True),
        _row("b", predicted=True, actual=False, stuffing_unavailable=True),
    ]
    result = gate_verdict(rows)
    assert result["verdict"] == "ALIVE"
    assert [r.id for r in result["degraded"]] == ["b"]


# --- confidence_review -----------------------------------------------------

def test_drop_beyond_threshold_is_flagged_for_human_review():
    deltas = {
        "small": (0.70, 0.65),
        "big": (0.80, 0.80 - CONFIDENCE_DROP_REVIEW - 0.01),
    }
    assert confidence_review(deltas) == ["big"]


def test_confidence_gain_is_never_flagged():
    # raw-only can outscore the fusion (RRF truncation reshuffles the pool);
    # a HIGHER number with the flag on is not a user-facing cost.
    assert confidence_review({"q": (0.60, 0.75)}) == []
