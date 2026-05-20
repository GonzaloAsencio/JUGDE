"""Tests unitarios para la lógica de chunking en ingest.py (sin Supabase)."""
import pytest
from scripts.ingest import (
    _approx_tokens,
    _split_into_sections,
    _make_chunk,
    _chunk_section,
    build_chunks,
)


# ---------------------------------------------------------------------------
# _approx_tokens
# ---------------------------------------------------------------------------

def test_approx_tokens_empty():
    assert _approx_tokens("") == 0


def test_approx_tokens_four_chars_is_one_token():
    assert _approx_tokens("abcd") == 1


def test_approx_tokens_proportional():
    assert _approx_tokens("a" * 400) == 100


# ---------------------------------------------------------------------------
# _split_into_sections
# ---------------------------------------------------------------------------

SAMPLE_MD = """\
# Title

Some intro text.

## Section One

Content of section one.

### Subsection 1.1

Subsection content.

## Section Two

Content of section two.
"""


def test_split_sections_count():
    sections = _split_into_sections(SAMPLE_MD)
    assert len(sections) == 4


def test_split_sections_levels():
    sections = _split_into_sections(SAMPLE_MD)
    assert [s["level"] for s in sections] == [1, 2, 3, 2]


def test_split_sections_headers():
    sections = _split_into_sections(SAMPLE_MD)
    assert sections[0]["header"] == "Title"
    assert sections[1]["header"] == "Section One"
    assert sections[2]["header"] == "Subsection 1.1"
    assert sections[3]["header"] == "Section Two"


def test_split_sections_content_includes_header_line():
    sections = _split_into_sections(SAMPLE_MD)
    assert "# Title" in sections[0]["content"]
    assert "Content of section one." in sections[1]["content"]


def test_split_sections_empty_markdown_returns_empty():
    assert _split_into_sections("") == []


def test_split_sections_no_headers_returns_empty():
    assert _split_into_sections("Just plain text, no headers.") == []


# ---------------------------------------------------------------------------
# _make_chunk
# ---------------------------------------------------------------------------

def test_make_chunk_has_required_keys():
    chunk = _make_chunk("content", "section", "parent", "rulebook", "doc")
    assert set(chunk.keys()) == {
        "id", "content", "source_type", "source_document",
        "section", "parent_section", "corpus_version",
    }


def test_make_chunk_id_is_valid_uuid():
    chunk = _make_chunk("hello", "sec", "par", "rulebook", "mydoc")
    import uuid as _uuid
    parsed = _uuid.UUID(chunk["id"])  # raises ValueError if invalid
    assert parsed.version == 5


def test_make_chunk_is_deterministic():
    a = _make_chunk("same content", "s", "p", "rulebook", "doc")
    b = _make_chunk("same content", "s", "p", "rulebook", "doc")
    assert a["id"] == b["id"]


def test_make_chunk_different_content_different_id():
    a = _make_chunk("content A", "s", "p", "rulebook", "doc")
    b = _make_chunk("content B", "s", "p", "rulebook", "doc")
    assert a["id"] != b["id"]


# ---------------------------------------------------------------------------
# _chunk_section
# ---------------------------------------------------------------------------

SHORT_SECTION = {
    "header": "Short",
    "level": 2,
    "content": "## Short\n\nThis is short content.",
}


def test_chunk_section_short_yields_one_chunk():
    chunks = _chunk_section(SHORT_SECTION, "rulebook", "doc")
    assert len(chunks) == 1
    assert chunks[0]["content"] == SHORT_SECTION["content"]


def test_chunk_section_short_metadata():
    chunk = _chunk_section(SHORT_SECTION, "rulebook", "doc")[0]
    assert chunk["source_type"] == "rulebook"
    assert chunk["source_document"] == "doc"
    assert chunk["section"] == "Short"


def _make_long_section(n_paragraphs: int) -> dict:
    """Sección con n_paragraphs de ~114 chars (~28 tokens) para superar CHUNK_SIZE=512."""
    paragraphs = [f"Paragraph {i}: " + "x" * 100 for i in range(n_paragraphs)]
    content = "## Long Section\n\n" + "\n\n".join(paragraphs)
    return {"header": "Long Section", "level": 2, "content": content}


def test_chunk_section_long_yields_multiple_chunks():
    section = _make_long_section(30)  # ~843 tokens > CHUNK_SIZE 512
    chunks = _chunk_section(section, "rulebook", "doc")
    assert len(chunks) > 1


def test_chunk_section_overlap_last_para_shared():
    """El último párrafo de chunk[0] debe ser el primero de chunk[1] (overlap)."""
    section = _make_long_section(30)
    chunks = _chunk_section(section, "rulebook", "doc")
    last_para_chunk0 = chunks[0]["content"].split("\n\n")[-1]
    first_para_chunk1 = chunks[1]["content"].split("\n\n")[0]
    assert last_para_chunk0 == first_para_chunk1


# ---------------------------------------------------------------------------
# build_chunks
# ---------------------------------------------------------------------------

def test_build_chunks_missing_file_returns_empty(tmp_path):
    chunks = build_chunks(str(tmp_path / "nonexistent.md"), "rulebook")
    assert chunks == []


def test_build_chunks_produces_one_chunk_per_section(tmp_path):
    md = (
        "# Title\n\nIntro.\n\n"
        "## Section A\n\nContent A.\n\n"
        "## Section B\n\nContent B.\n"
    )
    f = tmp_path / "test.md"
    f.write_text(md, encoding="utf-8")
    chunks = build_chunks(str(f), "rulebook")
    assert len(chunks) == 3


def test_build_chunks_source_type_propagated(tmp_path):
    md = "# Title\n\nContent.\n"
    f = tmp_path / "errata.md"
    f.write_text(md, encoding="utf-8")
    chunks = build_chunks(str(f), "errata")
    assert all(c["source_type"] == "errata" for c in chunks)


def test_build_chunks_source_document_is_stem(tmp_path):
    md = "# Title\n\nContent.\n"
    f = tmp_path / "errata.md"
    f.write_text(md, encoding="utf-8")
    chunks = build_chunks(str(f), "errata")
    assert all(c["source_document"] == "errata" for c in chunks)


# ---------------------------------------------------------------------------
# _chunk_section — fallback rule-split
# ---------------------------------------------------------------------------

def _make_giant_rule_block() -> dict:
    """Un único párrafo sin \\n\\n con números de regla embebidos (~3200 tokens)."""
    rule_block = " ".join(
        f"{800 + i}. This is a long rule description that takes up space. " * 15
        for i in range(8)
    )
    return {"content": rule_block, "header": "Keywords", "level": 2}


def test_chunk_section_falls_back_to_rule_split_for_single_huge_paragraph():
    section = _make_giant_rule_block()
    chunks = _chunk_section(section, "rulebook", "rulebook.md")
    assert len(chunks) > 1, "Fallback rule-split debe generar múltiples chunks"


def test_chunk_section_fallback_chunks_contain_rule_numbers():
    section = _make_giant_rule_block()
    chunks = _chunk_section(section, "rulebook", "rulebook.md")
    rule_nums = {c["content"].split(".")[0].strip() for c in chunks}
    assert any(n.isdigit() and len(n) == 3 for n in rule_nums)
