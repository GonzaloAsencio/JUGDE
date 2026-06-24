"""Unit tests for the lineage chunker's pure logic (breadcrumb inheritance).

The embedding/recall parts run manually. These pin the deterministic rule that
each chunk inherits the most-recent top-level rule's number + title.
"""
from scripts.lineage_offline_probe import (
    _unit_breadcrumbs,
    chunk_rulebook_lineage,
    rule_title,
)


def test_rule_title_first_bold():
    assert rule_title("383. **Triggered Abilities** are repeatable.") == "Triggered Abilities"


def test_rule_title_none_without_bold():
    assert rule_title("383. plain text no bold") is None


def test_breadcrumb_inherits_across_subrules():
    units = [
        "383. **Triggered Abilities** are repeatable.",
        "383.3. When a Condition is met.",
        "383.4.e. **Attack Triggers** are Triggered Abilities.",
    ]
    crumbs = _unit_breadcrumbs(units)
    assert crumbs == [("383", "Triggered Abilities")] * 3


def test_breadcrumb_switches_on_next_top_level():
    units = [
        "383. **Triggered Abilities** repeatable.",
        "383.4.e. Attack Triggers text.",
        "459. **Combat** is the phase.",
        "459.2.d. Some combat sub-rule.",
    ]
    crumbs = _unit_breadcrumbs(units)
    assert crumbs[0] == ("383", "Triggered Abilities")
    assert crumbs[1] == ("383", "Triggered Abilities")
    assert crumbs[2] == ("459", "Combat")
    assert crumbs[3] == ("459", "Combat")


def test_breadcrumb_none_before_any_top_level():
    units = ["383.4.e. orphan sub-rule with no preceding top-level"]
    assert _unit_breadcrumbs(units) == [None]


def test_chunk_header_carries_parent_breadcrumb():
    # A section whose H3 header is the coarse "360. Abilities" but the rule is 383.x:
    # the lineage chunk header must name Rule 383: Triggered Abilities.
    content = (
        "### 360. Abilities\n"
        "383. **Triggered Abilities** are repeatable effects.\n"
        "383.4.e. **Attack Triggers** trigger when a unit attacks.\n"
    )
    chunks = chunk_rulebook_lineage(content, "360. Abilities", "parent", "rulebook", {})
    assert chunks, "expected at least one chunk"
    assert all("Rule 383: Triggered Abilities" in c["content"] for c in chunks)
