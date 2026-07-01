"""Unit tests for card_presence_probe pure logic (no DB, no LLM).

The probe measures the entity-aware retrieval contract: every card name DETECTED
in a question must land in the final context. These tests cover the deterministic
helpers that decide whether a named card is present and aggregate the delivery
rate; the DB/embedder-driven main is exercised manually, not here.
"""
from types import SimpleNamespace

from scripts.card_presence_probe import card_name_of, card_present, delivery_rate


def _card(name: str | None = None, source_type: str = "card", extra: str = ""):
    """Lightweight Chunk stand-in: only .content and .source_type are read."""
    content = f"## Header\n**Name**: {name}\n**Set**: X\n{extra}" if name is not None else extra
    return SimpleNamespace(content=content, source_type=source_type)


# ---------------------------------------------------------------------------
# card_name_of
# ---------------------------------------------------------------------------

def test_card_name_parsed_from_card_chunk():
    assert card_name_of(_card("Vex - Apathetic")) == "Vex - Apathetic"


def test_card_name_none_for_non_card():
    assert card_name_of(_card("Vex - Apathetic", source_type="rulebook")) is None


def test_card_name_none_when_no_name_field():
    assert card_name_of(SimpleNamespace(content="## Header\nno name here", source_type="card")) is None


# ---------------------------------------------------------------------------
# card_present
# ---------------------------------------------------------------------------

def test_present_exact_match():
    chunks = [_card("Vex - Apathetic")]
    assert card_present("Vex Apathetic", chunks) is True


def test_present_ignores_variant_suffix():
    chunks = [_card("Jhin - Virtuoso (Overnumbered)")]
    assert card_present("Jhin Virtuoso", chunks) is True


def test_present_case_insensitive():
    chunks = [_card("Marching Orders")]
    assert card_present("marching orders", chunks) is True


def test_absent_when_no_card_matches():
    chunks = [_card("Tideturner"), _card("Hidden Blade")]
    assert card_present("Marching Orders", chunks) is False


def test_absent_when_only_non_card_chunks():
    # A rulebook chunk that happens to mention the name must NOT count as the card.
    chunks = [_card("Marching Orders", source_type="rulebook")]
    assert card_present("Marching Orders", chunks) is False


# ---------------------------------------------------------------------------
# delivery_rate
# ---------------------------------------------------------------------------

def test_delivery_rate_all_present():
    records = [
        {"detected": ["a", "b"], "present": ["a", "b"]},
        {"detected": ["c"], "present": ["c"]},
    ]
    out = delivery_rate(records)
    assert out["detected"] == 3
    assert out["present"] == 3
    assert out["rate"] == 1.0
    assert out["no_card_questions"] == 0


def test_delivery_rate_partial():
    records = [{"detected": ["a", "b"], "present": ["a"]}]
    out = delivery_rate(records)
    assert out["detected"] == 2
    assert out["present"] == 1
    assert out["rate"] == 0.5


def test_delivery_rate_counts_questions_without_cards():
    records = [
        {"detected": [], "present": []},
        {"detected": ["a"], "present": ["a"]},
    ]
    out = delivery_rate(records)
    assert out["no_card_questions"] == 1
    assert out["detected"] == 1


def test_delivery_rate_zero_detected_no_division_error():
    records = [{"detected": [], "present": []}]
    out = delivery_rate(records)
    assert out["detected"] == 0
    assert out["rate"] == 0.0
