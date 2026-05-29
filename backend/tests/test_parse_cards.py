import copy
import json
from pathlib import Path

import pytest

from scripts.parse_cards import (
    _filter_cards,
    _render_card,
    _render_markdown,
    parse_cards,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_JSON = FIXTURES / "cards_sample.json"


@pytest.fixture
def sample_cards() -> list[dict]:
    return json.loads(SAMPLE_JSON.read_text(encoding="utf-8"))


@pytest.fixture
def yasuo(sample_cards) -> dict:
    return copy.deepcopy(sample_cards[0])


# ---------------------------------------------------------------------------
# _render_card — single-card rendering
# ---------------------------------------------------------------------------

def test_render_uses_clean_name_as_h2_section(yasuo):
    md = _render_card(yasuo)
    assert md.startswith("## yasuo\n")


def test_render_includes_display_name(yasuo):
    md = _render_card(yasuo)
    assert "**Name**: Yasuo" in md


def test_render_set_line_uses_label_and_riftbound_id(yasuo):
    md = _render_card(yasuo)
    assert "**Set**: Origins (ORI-042)" in md


def test_render_includes_rarity(yasuo):
    md = _render_card(yasuo)
    assert "**Rarity**: Legendary" in md


def test_render_joins_multiple_domains(yasuo):
    yasuo["classification"]["domain"] = ["Body", "Mind"]
    md = _render_card(yasuo)
    assert "**Domain**: Body, Mind" in md


def test_render_includes_full_stat_line_for_unit(yasuo):
    md = _render_card(yasuo)
    assert "**Energy**: 3" in md
    assert "**Might**: 4" in md
    assert "**Power**: 3" in md
    assert "**Type**: Unit" in md


def test_render_omits_missing_stats(sample_cards):
    counterspell = sample_cards[1]
    md = _render_card(counterspell)
    assert "**Energy**: 2" in md
    assert "**Type**: Spell" in md
    assert "**Might**" not in md
    assert "**Power**" not in md


def test_render_joins_tags_with_commas(yasuo):
    md = _render_card(yasuo)
    assert "**Tags**: Accelerate, Quick-Draw" in md


def test_render_omits_tags_line_when_empty(sample_cards):
    shen = sample_cards[3]
    md = _render_card(shen)
    assert "**Tags**" not in md


def test_render_uses_plain_text_not_rich(yasuo):
    md = _render_card(yasuo)
    assert "When Yasuo enters the board, draw a card." in md
    assert "<p>" not in md


def test_render_includes_flavor_when_present(yasuo):
    md = _render_card(yasuo)
    assert '*Flavor*: "A wanderer\'s path is his own."' in md


def test_render_omits_flavor_when_missing(sample_cards):
    counterspell = sample_cards[1]
    md = _render_card(counterspell)
    assert "*Flavor*" not in md


def test_render_preserves_multiline_card_text(yasuo):
    md = _render_card(yasuo)
    assert "When Yasuo enters the board" in md
    assert "Activated: pay 1, ready Yasuo." in md


# ---------------------------------------------------------------------------
# _filter_cards — dedupe + alternate_art exclusion
# ---------------------------------------------------------------------------

def test_filter_excludes_alternate_art(sample_cards):
    result = _filter_cards(sample_cards)
    assert not any(c["metadata"]["alternate_art"] for c in result)


def test_filter_dedupes_by_riftbound_id(sample_cards):
    result = _filter_cards(sample_cards)
    riftbound_ids = [c["riftbound_id"] for c in result]
    assert len(riftbound_ids) == len(set(riftbound_ids))


def test_filter_keeps_distinct_cards(sample_cards):
    result = _filter_cards(sample_cards)
    names = sorted(c["name"] for c in result)
    assert names == ["Counterspell", "Shen", "Yasuo"]


# ---------------------------------------------------------------------------
# _render_markdown — full corpus
# ---------------------------------------------------------------------------

def test_render_markdown_produces_one_section_per_unique_card(sample_cards):
    md = _render_markdown(sample_cards)
    h2_count = sum(1 for line in md.splitlines() if line.startswith("## "))
    assert h2_count == 3  # Yasuo, Counterspell, Shen — alternate art + duplicate filtered


def test_render_markdown_separates_cards_with_blank_line(sample_cards):
    md = _render_markdown(sample_cards)
    assert "\n\n## " in md


def test_render_markdown_skips_card_missing_clean_name():
    broken = {"name": "Broken", "riftbound_id": "X-1", "metadata": {"alternate_art": False}}
    md = _render_markdown([broken])
    assert md.strip() == ""


# ---------------------------------------------------------------------------
# parse_cards — entry point with local JSON
# ---------------------------------------------------------------------------

def test_parse_cards_from_local_json_path(tmp_path, sample_cards):
    fixture = tmp_path / "cards.json"
    fixture.write_text(json.dumps(sample_cards), encoding="utf-8")
    md = parse_cards(fixture)
    assert "## yasuo" in md
    assert "## counterspell" in md
    assert "## shen" in md
