import copy
import json
from pathlib import Path

import pytest

from scripts.parse_cards import (
    _filter_cards,
    _render_card,
    _render_markdown,
    build_card_index,
    parse_cards,
    serialize_card_index_ts,
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


# ---------------------------------------------------------------------------
# build_card_index — frontend lookup index generation
# ---------------------------------------------------------------------------

def test_build_card_index_excludes_alternate_art(sample_cards):
    """rc-003 in the fixture has alternate_art=true — must not appear in the index."""
    index = build_card_index(sample_cards)
    rb_ids = [e["riftbound_id"] for e in index]
    assert rb_ids.count("ORI-042") <= 1  # alt version must be filtered


def test_build_card_index_excludes_signature(yasuo):
    sig = copy.deepcopy(yasuo)
    sig["riftbound_id"] = "ORI-042s"
    sig["metadata"]["signature"] = True
    index = build_card_index([sig])
    assert index == []


def test_build_card_index_excludes_overnumbered(yasuo):
    over = copy.deepcopy(yasuo)
    over["riftbound_id"] = "ORI-042o"
    over["metadata"]["overnumbered"] = True
    index = build_card_index([over])
    assert index == []


def test_build_card_index_dedupes_by_clean_name(sample_cards):
    """Fixture has 3 Yasuo records (rc-001, rc-003 alt, rc-005 reprint) — only one survives."""
    index = build_card_index(sample_cards)
    clean_names = [e["clean_name"] for e in index]
    assert clean_names.count("yasuo") == 1


def test_build_card_index_first_match_wins_on_dedupe(sample_cards):
    """When multiple non-special cards share a clean_name, the first one in the input list wins."""
    index = build_card_index(sample_cards)
    yasuo_entry = next(e for e in index if e["clean_name"] == "yasuo")
    assert yasuo_entry["riftbound_id"] == "ORI-042"
    assert yasuo_entry["image_url"] == "https://example.com/yasuo.png"  # rc-001's image, not rc-005's


def test_build_card_index_entry_has_exact_four_fields(sample_cards):
    index = build_card_index(sample_cards)
    for entry in index:
        assert set(entry.keys()) == {"clean_name", "image_url", "set_label", "riftbound_id"}


def test_build_card_index_maps_fields_correctly(sample_cards):
    index = build_card_index(sample_cards)
    yasuo_entry = next(e for e in index if e["clean_name"] == "yasuo")
    assert yasuo_entry["set_label"] == "Origins"
    assert yasuo_entry["riftbound_id"] == "ORI-042"
    assert yasuo_entry["image_url"].startswith("https://")


def test_build_card_index_skips_card_missing_clean_name():
    broken = {
        "name": "Broken",
        "riftbound_id": "BR-1",
        "metadata": {"alternate_art": False, "signature": False, "overnumbered": False},
        "media": {"image_url": "https://x"},
        "set": {"label": "Test"},
    }
    assert build_card_index([broken]) == []


def test_build_card_index_skips_card_missing_image_url(yasuo):
    """A card without an image_url can't be previewed — drop it from the index."""
    no_img = copy.deepcopy(yasuo)
    no_img["media"] = {}
    assert build_card_index([no_img]) == []


def test_build_card_index_returns_full_sample(sample_cards):
    """End-to-end on the fixture: 3 unique cards after all filters."""
    index = build_card_index(sample_cards)
    clean_names = sorted(e["clean_name"] for e in index)
    assert clean_names == ["counterspell", "shen", "yasuo"]


# ---------------------------------------------------------------------------
# serialize_card_index_ts — emit a TypeScript module
# ---------------------------------------------------------------------------

def test_serialize_ts_starts_with_auto_generated_banner(sample_cards):
    ts = serialize_card_index_ts(build_card_index(sample_cards))
    assert ts.startswith("// AUTO-GENERATED")


def test_serialize_ts_exports_interface(sample_cards):
    ts = serialize_card_index_ts(build_card_index(sample_cards))
    assert "export interface CardIndexEntry" in ts
    assert "clean_name: string" in ts
    assert "image_url: string" in ts
    assert "set_label: string" in ts
    assert "riftbound_id: string" in ts


def test_serialize_ts_exports_const_array_as_const(sample_cards):
    ts = serialize_card_index_ts(build_card_index(sample_cards))
    assert "export const CARD_INDEX: readonly CardIndexEntry[]" in ts
    assert "as const" in ts


def test_serialize_ts_contains_entry_data(sample_cards):
    ts = serialize_card_index_ts(build_card_index(sample_cards))
    assert '"yasuo"' in ts
    assert '"shen"' in ts
    assert '"counterspell"' in ts


def test_serialize_ts_escapes_special_characters_safely():
    """If a card name contains a double quote, the TS literal must remain parseable."""
    entries = [{
        "clean_name": 'name with "quote"',
        "image_url": "https://x",
        "set_label": "Test",
        "riftbound_id": "TS-1",
    }]
    ts = serialize_card_index_ts(entries)
    # JSON-encoded quote is \" — must appear, must not appear as unescaped
    assert '\\"quote\\"' in ts
