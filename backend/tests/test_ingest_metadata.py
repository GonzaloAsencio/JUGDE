"""TDD para metadata por expansión en ingest.py: _detect_set + _make_chunk."""
from scripts.ingest import _detect_set, _make_chunk


# ---------------------------------------------------------------------------
# _detect_set
# ---------------------------------------------------------------------------

def test_detect_set_rulebook_is_core():
    assert _detect_set("rulebook") == "core"


def test_detect_set_tournament_is_core():
    assert _detect_set("tournament_rules") == "core"


def test_detect_set_patch_notes_by_suffix():
    assert _detect_set("patch_notes_origins") == "origins"
    assert _detect_set("patch_notes_spiritforged") == "spiritforged"
    assert _detect_set("patch_notes_unleashed") == "unleashed"


def test_detect_set_faq_by_suffix():
    assert _detect_set("faq_origins") == "origins"
    assert _detect_set("faq_unleashed") == "unleashed"


def test_detect_set_errata_by_suffix():
    assert _detect_set("errata_origins") == "origins"
    assert _detect_set("errata_spiritforged") == "spiritforged"


def test_detect_set_cards_uses_content_set_field():
    content = "## Yasuo\n**Set**: Origins (ORI-042) | **Rarity**: Legendary"
    assert _detect_set("cards", content) == "origins"


def test_detect_set_cards_spiritforged_from_content():
    content = "## Rell\n**Set**: Spiritforged (SFD-010)"
    assert _detect_set("cards", content) == "spiritforged"


def test_detect_set_cards_without_set_field_defaults_core():
    assert _detect_set("cards", "## NoSet\n**Type**: Unit") == "core"


def test_detect_set_unknown_stem_defaults_core():
    assert _detect_set("something_else") == "core"


# ---------------------------------------------------------------------------
# _make_chunk — metadata
# ---------------------------------------------------------------------------

def test_make_chunk_includes_metadata_key():
    chunk = _make_chunk("content", "section", "parent", "rulebook", "doc", metadata={"set": "core"})
    assert "metadata" in chunk
    assert chunk["metadata"] == {"set": "core"}


def test_make_chunk_metadata_defaults_to_empty_dict():
    chunk = _make_chunk("content", "section", "parent", "rulebook", "doc")
    assert chunk["metadata"] == {}


def test_make_chunk_id_unaffected_by_metadata():
    """El ID determinístico NO debe depender de metadata (solo source_document + content)."""
    a = _make_chunk("same", "s", "p", "rulebook", "doc", metadata={"set": "origins"})
    b = _make_chunk("same", "s", "p", "rulebook", "doc", metadata={"set": "unleashed"})
    assert a["id"] == b["id"]
