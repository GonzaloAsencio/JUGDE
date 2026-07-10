"""TDD para el chunking fino del rulebook (reglas NNN. sin partir a la mitad)."""
import re

from scripts.ingest import (
    CHUNK_SIZE,
    RULEBOOK_CHUNK_SIZE,
    _approx_tokens,
    _chunk_section,
)


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


def test_small_rulebook_section_with_multiple_rules_still_splits():
    """Strategy A: a rulebook section that fits under CHUNK_SIZE but holds several
    rules must STILL be finely chunked. Packing many rules into one chunk dilutes
    its embedding — a probe measured those buried rules never retrieving."""
    section = _make_rule_section(6, rule_len=200)  # ~310 tokens, UNDER CHUNK_SIZE 512
    assert _approx_tokens(section["content"]) <= CHUNK_SIZE  # guard: would have been 1 chunk before
    chunks = _chunk_section(section, "rulebook", "rulebook")
    assert len(chunks) > 1, "rulebook rules must be finely chunked even under CHUNK_SIZE"


def test_rulebook_chunks_within_rulebook_budget():
    """Each rulebook chunk must respect the smaller rulebook budget (not just CHUNK_SIZE)."""
    section = _make_rule_section(30, rule_len=180)
    chunks = _chunk_section(section, "rulebook", "rulebook")
    oversized = [c for c in chunks if _approx_tokens(c["content"]) > RULEBOOK_CHUNK_SIZE]
    assert oversized == []


def test_rulebook_budget_is_smaller_than_global():
    """The whole point of strategy A: rulebook chunks are finer than the global budget."""
    assert RULEBOOK_CHUNK_SIZE < CHUNK_SIZE


def _keywords_style_section() -> dict:
    """Sección estilo '800. Keywords': un solo header markdown con títulos de regla
    internos como texto plano (`809. **Deflect**`) — la estructura real del rulebook
    donde viven los keywords. Diagnóstico 2026-07-10: los chunks heredaban la sección
    gruesa '800. Keywords', así que tagged_lookup('deflect') no encontraba NADA y el
    embedding del chunk no llevaba el nombre del keyword en su header."""
    body = [
        "### 800. Keywords",
        "808. **Deathknell**",
        "808.1. Deathknell is a triggered ability. " + "x" * 150,
        "808.2. Each instance triggers separately. " + "x" * 150,
        "809. **Deflect**",
        "809.1. Deflect is a Passive Ability keyword. " + "x" * 150,
        "809.2. Deflect imposes an additional cost. " + "x" * 150,
    ]
    return {"header": "800. Keywords", "level": 3, "content": "\n".join(body)}


def test_rulebook_chunks_take_inner_rule_title_as_section():
    """Un chunk que contiene 809.x debe llevar section '809. Deflect', no la
    sección madre '800. Keywords' — de eso depende tagged_lookup (section ILIKE)."""
    chunks = _chunk_section(_keywords_style_section(), "rulebook", "rulebook")
    deflect_chunks = [c for c in chunks if "809.1." in c["content"]]
    assert deflect_chunks, "debe existir un chunk con 809.1"
    assert all(c["section"] == "809. Deflect" for c in deflect_chunks)


def test_rulebook_chunks_never_span_rule_titles():
    """Un chunk no mezcla familias: nada de 808.x y 809.x juntos aunque quepan."""
    chunks = _chunk_section(_keywords_style_section(), "rulebook", "rulebook")
    for c in chunks:
        has_808 = "808." in c["content"]
        has_809 = "809." in c["content"]
        assert not (has_808 and has_809), f"chunk cruza familias: {c['content'][:60]!r}"


def test_rulebook_chunk_embedded_header_carries_rule_title():
    """El header prependido al contenido (lo que se embebe) debe nombrar la regla:
    '### 809. Deflect' — así el coseno ve el nombre del keyword."""
    chunks = _chunk_section(_keywords_style_section(), "rulebook", "rulebook")
    deflect_chunks = [c for c in chunks if "809.1." in c["content"]]
    assert all(c["content"].startswith("### 809. Deflect") for c in deflect_chunks)


def test_rulebook_section_without_inner_titles_keeps_header():
    """Secciones sin títulos internos NNN. **Title** conservan el header original."""
    section = _make_rule_section(6, rule_len=200)
    chunks = _chunk_section(section, "rulebook", "rulebook")
    assert all(c["section"] == "500. Big Section" for c in chunks)


def test_header_only_section_produces_no_chunk():
    """Una sección que es solo el header (sin cuerpo) no debe generar un chunk basura."""
    section = {"header": "100. Game Concepts", "level": 2, "content": "## 100. Game Concepts"}
    chunks = _chunk_section(section, "rulebook", "rulebook")
    assert chunks == []
