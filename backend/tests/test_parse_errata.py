"""TDD para el parser de erratas (New/Old text + set por H1 interno)."""
from scripts.parse_errata import (
    _set_from_h1,
    parse_errata_doc,
    render_errata_md,
)


# ---------------------------------------------------------------------------
# _set_from_h1
# ---------------------------------------------------------------------------

def test_set_from_h1_origins():
    assert _set_from_h1("Origins Cards") == "origins"


def test_set_from_h1_spiritforged():
    assert _set_from_h1("Spiritforged Cards") == "spiritforged"


def test_set_from_h1_unleashed():
    assert _set_from_h1("Unleashed Cards") == "unleashed"


def test_set_from_h1_non_set_header_returns_none():
    assert _set_from_h1("Card Errata") is None
    assert _set_from_h1("Summary") is None


# ---------------------------------------------------------------------------
# parse_errata_doc — default-set document (Origins Card Errata)
# ---------------------------------------------------------------------------

_ORIGINS_DOC = """\
# Riftbound: Origins Card Errata

## Overview

Some intro text, not a card.

# Card Errata

## Baited Hook

### New Text

```text
Kill a friendly unit. Banish then play.
```

### Old Text

```text
Kill a friendly unit. Play.
```

## Dune Drake

### New Text

```text
When I attack, give me +2 this turn.
```

### Old Text

```text
When I attack, give me +2.
```
"""


def test_parse_default_set_doc_extracts_only_real_cards():
    cards = parse_errata_doc(_ORIGINS_DOC, default_set="origins")
    names = [c["card"] for c in cards]
    # "Overview" has no New Text → must be excluded
    assert names == ["Baited Hook", "Dune Drake"]


def test_parse_default_set_assigns_default_set():
    cards = parse_errata_doc(_ORIGINS_DOC, default_set="origins")
    assert all(c["set"] == "origins" for c in cards)


def test_parse_new_and_old_text_captured_without_fences():
    cards = parse_errata_doc(_ORIGINS_DOC, default_set="origins")
    baited = next(c for c in cards if c["card"] == "Baited Hook")
    assert baited["new_text"] == "Kill a friendly unit. Banish then play."
    assert baited["old_text"] == "Kill a friendly unit. Play."


# ---------------------------------------------------------------------------
# parse_errata_doc — multi-set document (Unleashed Errata)
# ---------------------------------------------------------------------------

_MULTI_DOC = """\
# Unleashed Errata Updates

Intro paragraph.

# Spiritforged Cards

## Guards!

### New Text

Play a token. Then do this: ready it.

### Old Text

Play a token. You may ready it.

# Unleashed Cards

## Death from Below

### New Text

Kill a unit. Then do this: play from trash.

### Old Text

Kill a unit. You may play from trash.
"""


def test_parse_multi_set_routes_by_internal_h1():
    cards = parse_errata_doc(_MULTI_DOC, default_set="unleashed")
    by_name = {c["card"]: c["set"] for c in cards}
    assert by_name["Guards!"] == "spiritforged"
    assert by_name["Death from Below"] == "unleashed"


# ---------------------------------------------------------------------------
# render_errata_md
# ---------------------------------------------------------------------------

def test_render_new_text_is_body_old_text_is_marked():
    cards = [{
        "card": "Dune Drake",
        "set": "origins",
        "new_text": "When I attack, give me +2 this turn.",
        "old_text": "When I attack, give me +2.",
    }]
    md = render_errata_md(cards, set_name="origins")
    assert "## Dune Drake" in md
    assert "When I attack, give me +2 this turn." in md
    # Old text must be present but clearly marked as historical
    assert "Texto anterior (reemplazado):" in md
    # The new text must appear BEFORE the historical marker
    assert md.index("give me +2 this turn") < md.index("Texto anterior")


def test_render_skips_old_block_when_no_old_text():
    cards = [{"card": "X", "set": "origins", "new_text": "New only.", "old_text": None}]
    md = render_errata_md(cards, set_name="origins")
    assert "New only." in md
    assert "Texto anterior" not in md
