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
    # Correct for what THIS function asks ("which refs are missing?"): none are.
    # Note it deliberately does NOT mean "everything is covered" — that is
    # fully_covered's question, and it answers False for {} on purpose. diagnose
    # must not conflate the two; an unparseable rule_reference is guarded there.
    assert missing_refs({}) == []


# ---------------------------------------------------------------------------
# classify_miss — the precondition it used to carry unenforced
#
# The old diagnose() filtered `first_covering_rank(refs, top) is not None ->
# continue`, which GUARANTEED top_chunks never covered the ref. That filter was
# removed (it hid partial-coverage gaps) but the classifier that depended on it
# was not updated: absence is now judged against the production context (top_k=5)
# while classification still runs against vector top-15. A gold reachable at
# rank 12 but absent from a 5-chunk context therefore hit classify_miss with a
# top that COVERS it, and A:granularity fired off the gold ITSELF rather than a
# sibling — sending the project down the chunk-lineage lever for what is really
# a ranking problem. Measured latent on corpus v2.2.1 (no absent ref is covered
# in top-15), which is luck, not construction. The classifier is now total.
# ---------------------------------------------------------------------------

def test_classify_reports_ranking_when_top_actually_covers_the_ref():
    # Gold IS retrievable — it just didn't survive into the production context.
    # That is a RANKING problem; calling it granularity picks the wrong lever.
    top = [_chunk("365.1. Deflect only applies to Permanents.")]
    assert classify_miss(["365.1"], top) == "C:ranking"


def test_classify_prefers_ranking_over_granularity_when_both_could_match():
    # A sibling (365.2) AND the gold itself (365.1) are present. Granularity
    # would fire on the shared 3-digit base; coverage is the stronger fact.
    top = [_chunk("365.2. Sibling text."), _chunk("365.1. The gold rule itself.")]
    assert classify_miss(["365.1"], top) == "C:ranking"


def test_classify_still_reports_granularity_when_only_a_sibling_is_present():
    top = [_chunk("383.4.d. A sibling that does not cover the gold.")]
    assert classify_miss(["383.4.e"], top) == "A:granularity"


def test_classify_single_missing_ref_is_not_rescued_by_another_family():
    # The per-ref unit in action: classifying 383.4.e ALONE against a top that
    # only has 459-family chunks correctly reports a semantic gap, where the
    # question-level call would have said granularity off the 459 sibling.
    top = [_chunk("459.2.a some rule in the 459 family")]
    assert classify_miss(["383.4.e"], top) == "B:semantic_gap"
