"""build_chunks propaga `set` por documento/carta.

El comportamiento de upsert_chunks (metadata, ON CONFLICT) se verifica ahora
contra Postgres real en tests/integration/test_ingest_db.py — los mocks no
pueden ejercitar execute_values (necesita mogrify real).
"""
from scripts.ingest import build_chunks


def test_build_chunks_errata_assigns_set_from_filename(tmp_path):
    f = tmp_path / "errata_origins.md"
    f.write_text("# Errata — Origins\n\n## Dune Drake\n\nWhen I attack, give me +2 this turn.\n", encoding="utf-8")
    chunks = build_chunks(str(f), "errata")
    assert chunks
    assert all(c["metadata"].get("set") == "origins" for c in chunks)


def test_build_chunks_rulebook_set_is_core(tmp_path):
    f = tmp_path / "rulebook.md"
    f.write_text("# Riftbound Core Rules\n\n## 100. Game Concepts\n\n### 101. Deck Construction\n\nSome rule body.\n", encoding="utf-8")
    chunks = build_chunks(str(f), "rulebook")
    assert chunks
    assert all(c["metadata"].get("set") == "core" for c in chunks)


def test_build_chunks_cards_set_is_per_card(tmp_path):
    cards_md = (
        "## Yasuo\n**Set**: Origins (ORI-042)\n\n**Text**:\nDraw a card.\n\n"
        "## Rell\n**Set**: Spiritforged (SFD-010)\n\n**Text**:\nTank.\n"
    )
    f = tmp_path / "cards.md"
    f.write_text(cards_md, encoding="utf-8")
    chunks = build_chunks(str(f), "card")
    by_section = {c["section"]: c["metadata"].get("set") for c in chunks}
    assert by_section["Yasuo"] == "origins"
    assert by_section["Rell"] == "spiritforged"
