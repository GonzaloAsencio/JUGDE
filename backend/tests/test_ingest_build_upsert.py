"""TDD: build_chunks propaga set por documento/carta + upsert persiste metadata."""
from unittest.mock import MagicMock

from scripts.ingest import build_chunks, upsert_chunks


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


# ---------------------------------------------------------------------------
# upsert_chunks — metadata column
# ---------------------------------------------------------------------------

def _mock_conn():
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


def test_upsert_sql_includes_metadata_column():
    conn, cur = _mock_conn()
    chunk = {
        "id": "abc", "content": "c", "embedding": [0.0],
        "source_type": "errata", "source_document": "errata_origins",
        "section": "Dune Drake", "parent_section": "p",
        "corpus_version": "v2.0.0", "metadata": {"set": "origins"},
    }
    upsert_chunks(conn, [chunk])
    sql_used = cur.execute.call_args[0][0]
    assert "metadata" in sql_used


def test_upsert_passes_metadata_value():
    conn, cur = _mock_conn()
    chunk = {
        "id": "abc", "content": "c", "embedding": [0.0],
        "source_type": "errata", "source_document": "errata_origins",
        "section": "Dune Drake", "parent_section": "p",
        "corpus_version": "v2.0.0", "metadata": {"set": "origins"},
    }
    upsert_chunks(conn, [chunk])
    params = cur.execute.call_args[0][1]
    # psycopg2.extras.Json envuelve el dict; .adapted recupera el original.
    flat = [getattr(p, "adapted", p) for p in params]
    assert {"set": "origins"} in flat
