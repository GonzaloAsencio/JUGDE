"""Unit tests for the stratified subset sampler used by the eval harness.

The sampler lets us run a smaller, representative slice of the eval set when the
LLM free-tier budget can't absorb the full 40 questions in one run. It must be
deterministic (reproducible runs) and preserve the proportion of each stratum.
"""
from collections import Counter

from scripts.eval import select_by_ids, stratified_subset


def _q(id_, difficulty):
    return {"id": id_, "difficulty": difficulty, "question": f"q{id_}"}


def _dataset():
    # 5 'a', 3 'b', 2 'c' = 10 questions, in interleaved order.
    rows = (
        [("a", "a")] * 5 + [("b", "b")] * 3 + [("c", "c")] * 2
    )
    return [_q(f"eval-{i:03d}", diff) for i, (_, diff) in enumerate(rows)]


def test_limit_none_returns_all():
    qs = _dataset()
    assert stratified_subset(qs, None) == qs


def test_limit_ge_total_returns_all():
    qs = _dataset()
    assert stratified_subset(qs, 99) == qs


def test_limit_zero_returns_empty():
    assert stratified_subset(_dataset(), 0) == []


def test_returns_exactly_limit():
    qs = _dataset()
    assert len(stratified_subset(qs, 5)) == 5
    assert len(stratified_subset(qs, 7)) == 7


def test_preserves_strata_proportions_largest_remainder():
    # 5a/3b/2c, limit=5 -> raw a=2.5 b=1.5 c=1.0; floors 2/1/1 (sum 4);
    # remainder 1 goes to the largest fractional part, tie broken by key -> 'a'.
    # Expect a=3, b=1, c=1.
    qs = _dataset()
    counts = Counter(q["difficulty"] for q in stratified_subset(qs, 5))
    assert counts == {"a": 3, "b": 1, "c": 1}


def test_is_deterministic():
    qs = _dataset()
    a = [q["id"] for q in stratified_subset(qs, 6, seed=42)]
    b = [q["id"] for q in stratified_subset(qs, 6, seed=42)]
    assert a == b


def test_preserves_original_order():
    qs = _dataset()
    out = stratified_subset(qs, 6)
    ids = [q["id"] for q in out]
    assert ids == sorted(ids)  # dataset ids are already in order


def test_every_stratum_represented_when_room():
    qs = _dataset()
    counts = Counter(q["difficulty"] for q in stratified_subset(qs, 6))
    assert set(counts) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# select_by_ids — explicit disjoint batches
# ---------------------------------------------------------------------------

def test_select_by_ids_filters_and_preserves_order():
    qs = _dataset()
    out = select_by_ids(qs, ["eval-005", "eval-001", "eval-008"])
    # original order preserved, not the order given
    assert [q["id"] for q in out] == ["eval-001", "eval-005", "eval-008"]


def test_select_by_ids_ignores_unknown_ids():
    qs = _dataset()
    out = select_by_ids(qs, ["eval-099", "eval-003", "nope"])
    assert [q["id"] for q in out] == ["eval-003"]


def test_select_by_ids_empty_returns_empty():
    assert select_by_ids(_dataset(), []) == []
