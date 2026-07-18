"""Unit tests for the pure logic of scripts/hyde_model_probe.py.

Same contract as the other gate probes: runs are manual, the pre-committed
rule (plan §2.2) is pinned by CI so it cannot soften after the numbers are in.
"""
from scripts.hyde_model_probe import (
    ArmResult,
    QuestionResult,
    confidence_review,
    gate_verdict,
    regressions,
)
from scripts.hyde_skip_probe import CONFIDENCE_DROP_REVIEW


def _arm(covered=(), confidence=0.7, latency_s=1.0):
    return ArmResult(covered=frozenset(covered), confidence=confidence, latency_s=latency_s)


def _q(qid="q", main=(), cheap=(), persistent=(), main_conf=0.7, cheap_conf=0.7):
    return QuestionResult(
        id=qid, refs=tuple(sorted(set(main) | set(cheap))),
        main=_arm(main, main_conf), cheap=_arm(cheap, cheap_conf),
        persistent_regressions=frozenset(persistent),
    )


# --- regressions -----------------------------------------------------------

def test_regression_is_main_minus_cheap():
    assert regressions(frozenset({"383.3", "816"}), frozenset({"816"})) == {"383.3"}


def test_cheap_extra_coverage_is_not_a_regression():
    assert regressions(frozenset({"816"}), frozenset({"816", "383.3"})) == frozenset()


# --- gate_verdict ----------------------------------------------------------

def test_ties_and_wins_are_alive():
    results = [
        _q("a", main={"816"}, cheap={"816"}),
        _q("b", main={"131.4"}, cheap={"131.4", "425"}),  # a win
    ]
    assert gate_verdict(results) == "ALIVE"


def test_any_persistent_regression_kills():
    results = [
        _q("a", main={"816"}, cheap={"816"}),
        _q("b", main={"383.3"}, cheap=set(), persistent={"383.3"}),
    ]
    assert gate_verdict(results) == "DEAD"


def test_transient_regression_alone_does_not_kill():
    # Lost on the first candidate passage, recovered on the re-run: sampled
    # passages flip; only persistence is evidence (plan §2.2).
    results = [_q("a", main={"816"}, cheap=set(), persistent=())]
    assert gate_verdict(results) == "ALIVE"


def test_empty_results_is_a_broken_run_not_a_pass():
    assert gate_verdict([]) == "DEAD"


# --- confidence_review -----------------------------------------------------

def test_drop_beyond_shared_threshold_is_flagged():
    results = [
        _q("small", main_conf=0.70, cheap_conf=0.66),
        _q("big", main_conf=0.90, cheap_conf=0.90 - CONFIDENCE_DROP_REVIEW - 0.01),
    ]
    assert confidence_review(results) == ["big"]


def test_confidence_gain_is_never_flagged():
    assert confidence_review([_q("q", main_conf=0.60, cheap_conf=0.80)]) == []
