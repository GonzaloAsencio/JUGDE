"""Unit tests for family_nomination_probe pure logic (no DB, no LLM).

These decide the 3.11.1 gate, so they carry weight: a wrong lost_refs would
let a regression ship, and a wrong gained_refs would claim a win that isn't
there. The DB-driven run_probe/main are exercised manually.
"""
from types import SimpleNamespace

from scripts.family_nomination_probe import context_rule_sections, gained_refs, lost_refs


def _chunk(section: str | None):
    return SimpleNamespace(section=section)


# ---------------------------------------------------------------------------
# context_rule_sections — the TREATMENT's nomination rule
# ---------------------------------------------------------------------------

def test_picks_rule_sections_only():
    # Card and FAQ sections are not rule families and must not nominate one.
    chunks = [
        _chunk("383. Triggered Abilities"),
        _chunk("Vex - Apathetic"),
        _chunk("816. Temporary"),
        _chunk("Temporary on Attached Spinning Axe"),
    ]
    assert context_rule_sections(chunks) == ["383. Triggered Abilities", "816. Temporary"]


def test_deduplicates_repeated_family():
    # eval-020's shape: two chunks of the same family at ranks 4 and 6.
    chunks = [_chunk("383. Triggered Abilities"), _chunk("383. Triggered Abilities")]
    assert context_rule_sections(chunks) == ["383. Triggered Abilities"]


def test_tolerates_missing_section():
    assert context_rule_sections([_chunk(None), _chunk("816. Temporary")]) == ["816. Temporary"]


def test_empty_context():
    assert context_rule_sections([]) == []


# ---------------------------------------------------------------------------
# gained_refs / lost_refs — the gate itself
# ---------------------------------------------------------------------------

def test_gained_ref_is_one_absent_in_control_and_present_in_treatment():
    # eval-020's exact shape: 816 already there, 383.3.d arrives.
    control = {"816": 3, "383.3.d": None}
    treatment = {"816": 3, "383.3.d": 20}
    assert gained_refs(control, treatment) == ["383.3.d"]


def test_no_gain_when_already_covered():
    assert gained_refs({"816": 3}, {"816": 3}) == []


def test_lost_ref_is_one_present_in_control_and_absent_in_treatment():
    # Must be impossible (completion appends), so if this ever fires on real
    # data the append-only contract is broken and that IS the finding.
    assert lost_refs({"816": 3}, {"816": None}) == ["816"]


def test_nothing_lost_when_treatment_keeps_everything():
    assert lost_refs({"816": 3, "383.3.d": None}, {"816": 3, "383.3.d": 20}) == []


def test_a_ref_absent_in_both_is_neither_gained_nor_lost():
    control = {"365.1": None}
    treatment = {"365.1": None}
    assert gained_refs(control, treatment) == []
    assert lost_refs(control, treatment) == []


def test_rank_moving_deeper_is_not_a_loss():
    # Presence is the metric, not rank: appended chunks push nothing out.
    assert lost_refs({"816": 3}, {"816": 19}) == []
