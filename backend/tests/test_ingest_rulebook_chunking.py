"""TDD para el chunking fino del rulebook (reglas NNN. sin partir a la mitad)."""
import re

from scripts.ingest import _chunk_section, _approx_tokens, CHUNK_SIZE


def _make_rule_section(n_rules: int, rule_len: int = 220) -> dict:
    """Sección estilo rulebook: header H3 + reglas NNN. consecutivas (sin \\n\\n)."""
    body_lines = [f"### 500. Big Section"]
    for i in range(n_rules):
        num = 501 + i
        body_lines.append(f"{num}. " + "x" * rule_len)
    content = "\n".join(body_lines)
    return {"header": "500. Big Section", "level": 3, "content": content}


def test_oversized_rulebook_section_splits_into_multiple_chunks():
    section = _make_rule_section(30)  # claramente > CHUNK_SIZE
    chunks = _chunk_section(section, "rulebook", "rulebook")
    assert len(chunks) > 1


def test_rulebook_chunks_stay_within_size_budget():
    """Ningún chunk debe exceder CHUNK_SIZE cuando las reglas individuales caben."""
    section = _make_rule_section(30, rule_len=180)
    chunks = _chunk_section(section, "rulebook", "rulebook")
    oversized = [c for c in chunks if _approx_tokens(c["content"]) > CHUNK_SIZE]
    assert oversized == []


def test_rulebook_chunks_never_break_mid_rule():
    """Cada chunk (salvo el header solo) debe empezar en un límite de regla NNN."""
    section = _make_rule_section(30)
    chunks = _chunk_section(section, "rulebook", "rulebook")
    rule_start = re.compile(r"(?m)^\d{3,}\.")
    for c in chunks:
        # quitar la línea de header si está presente al inicio
        body = re.sub(r"^###[^\n]*\n+", "", c["content"]).lstrip()
        assert rule_start.match(body), f"chunk no empieza en regla: {body[:40]!r}"


def test_header_only_section_produces_no_chunk():
    """Una sección que es solo el header (sin cuerpo) no debe generar un chunk basura."""
    section = {"header": "100. Game Concepts", "level": 2, "content": "## 100. Game Concepts"}
    chunks = _chunk_section(section, "rulebook", "rulebook")
    assert chunks == []
