"""Unit tests for miss_diagnosis pure logic: numeric base + miss classification.

The DB/embedder-driven parts (diagnose, main) run manually, not here. These
cover the deterministic verdict that picks the lever for each chunking-miss.
"""
from types import SimpleNamespace

from scripts.miss_diagnosis import classify_miss, missing_refs, numeric_base


def _chunk(content: str):
    """Stand-in for a Chunk: only .content matters for classification."""
    return SimpleNamespace(content=content)


# ---------------------------------------------------------------------------
# numeric_base — 3-digit rule family
# ---------------------------------------------------------------------------

def test_numeric_base_of_subrule():
    assert numeric_base("383.4.e") == "383"


def test_numeric_base_of_bare_code():
    assert numeric_base("054") == "054"


def test_numeric_base_of_errata_ref_is_none():
    assert numeric_base("errata/origins/dark-child") is None


# ---------------------------------------------------------------------------
# classify_miss — granularity (sibling present) vs semantic gap (family absent)
# ---------------------------------------------------------------------------

def test_sibling_in_top_is_granularity():
    # gold 383.4.e missing, but a sibling 383.4.d is retrieved (same base 383,
    # not an ancestor that would cover it) -> granularity.
    top = [_chunk("383.4.d Some neighbouring sub-rule text.")]
    assert classify_miss(["383.4.e"], top) == "A:granularity"


def test_cousin_same_base_is_granularity():
    # different branch but same 3-digit family -> still granularity.
    top = [_chunk("383.7 Another rule in the 383 family.")]
    assert classify_miss(["383.4.e"], top) == "A:granularity"


def test_no_family_member_is_semantic_gap():
    top = [_chunk("207.1 unrelated rule"), _chunk("159 another unrelated rule")]
    assert classify_miss(["383.4.e"], top) == "B:semantic_gap"


def test_empty_top_is_semantic_gap():
    assert classify_miss(["459.2.d"], top := []) == "B:semantic_gap"


def test_multi_ref_matches_any_family():
    # ref list "383.4.e, 459.2.d": a 459-family sibling counts as granularity.
    top = [_chunk("459.2.a some rule in the 459 family")]
    assert classify_miss(["383.4.e", "459.2.d"], top) == "A:granularity"


def test_errata_only_refs_are_semantic_gap():
    # no numeric base to compare against -> defaults to semantic gap.
    top = [_chunk("103.2 whatever")]
    assert classify_miss(["errata/origins/x"], top) == "B:semantic_gap"


# ---------------------------------------------------------------------------
# missing_refs — diagnose the REF that's absent, not the question
#
# Why: diagnose() used to skip any question where first_covering_rank found ANY
# ref, so eval-020 (816 at rank 1, 383.3.d nowhere) and eval-030 (809.1 at rank
# 12, 365.1 nowhere) were NEVER diagnosed — the two partial-coverage gaps were
# invisible to the tool whose job is picking their lever. Classification has the
# same flaw at its own level (see test_multi_ref_matches_any_family: a 459
# sibling classifies a missing 383.4.e as granularity), which per-ref
# classification avoids by construction.
# ---------------------------------------------------------------------------

def test_missing_refs_returns_only_absent_ones():
    # eval-020's exact shape.
    assert missing_refs({"816": 1, "383.3.d": None}) == ["383.3.d"]


def test_missing_refs_empty_when_all_present():
    assert missing_refs({"816": 1, "383.3.d": 4}) == []


def test_missing_refs_all_absent():
    assert missing_refs({"347.3": None, "348": None}) == ["347.3", "348"]


def test_missing_refs_empty_map():
    assert missing_refs({}) == []


def test_classify_single_missing_ref_is_not_rescued_by_another_family():
    # The per-ref unit in action: classifying 383.4.e ALONE against a top that
    # only has 459-family chunks correctly reports a semantic gap, where the
    # question-level call would have said granularity off the 459 sibling.
    top = [_chunk("459.2.a some rule in the 459 family")]
    assert classify_miss(["383.4.e"], top) == "B:semantic_gap"
