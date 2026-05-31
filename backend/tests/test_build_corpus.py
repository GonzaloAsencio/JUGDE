"""TDD para la consolidación de erratas con precedencia por fecha."""
from scripts.build_corpus import consolidate_errata


def test_consolidate_groups_cards_by_set():
    docs = [
        {"date": "2025-10-27", "cards": [
            {"card": "Baited Hook", "set": "origins", "new_text": "v1", "old_text": None},
        ]},
        {"date": "2026-01-13", "cards": [
            {"card": "Arise!", "set": "spiritforged", "new_text": "vA", "old_text": None},
        ]},
    ]
    by_set = consolidate_errata(docs)
    assert set(by_set.keys()) == {"origins", "spiritforged"}
    assert by_set["origins"][0]["card"] == "Baited Hook"
    assert by_set["spiritforged"][0]["card"] == "Arise!"


def test_consolidate_latest_date_wins_for_same_card():
    docs = [
        {"date": "2025-10-27", "cards": [
            {"card": "Dune Drake", "set": "origins", "new_text": "OLD VERSION", "old_text": None},
        ]},
        {"date": "2026-04-02", "cards": [
            {"card": "Dune Drake", "set": "origins", "new_text": "NEW VERSION", "old_text": None},
        ]},
    ]
    by_set = consolidate_errata(docs)
    drakes = [c for c in by_set["origins"] if c["card"] == "Dune Drake"]
    assert len(drakes) == 1
    assert drakes[0]["new_text"] == "NEW VERSION"


def test_consolidate_ignores_doc_order_for_precedence():
    # Newer doc listed first, older second — newest must still win.
    docs = [
        {"date": "2026-04-02", "cards": [
            {"card": "X", "set": "unleashed", "new_text": "NEW", "old_text": None},
        ]},
        {"date": "2025-10-27", "cards": [
            {"card": "X", "set": "unleashed", "new_text": "OLD", "old_text": None},
        ]},
    ]
    by_set = consolidate_errata(docs)
    assert by_set["unleashed"][0]["new_text"] == "NEW"
