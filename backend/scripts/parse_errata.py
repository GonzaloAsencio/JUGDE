"""
Parsea documentos de errata de Riftbound a Markdown con el New Text vigente.

Formatos soportados:
  - Doc de un solo set (Origins Card Errata): cartas bajo "# Card Errata",
    todas con el `default_set`.
  - Doc multi-set (Spiritforged/Unleashed Errata): cartas agrupadas por
    H1 interno "# Origins Cards" / "# Spiritforged Cards" / "# Unleashed Cards".

Cada carta tiene un "### New Text" (vigente) y opcionalmente "### Old Text"
(histórico). El render deja el New Text como cuerpo y el Old Text claramente
etiquetado como reemplazado, para que el juez nunca cite texto viejo como actual.
"""
import re
from pathlib import Path

_SET_WORDS = ("origins", "spiritforged", "unleashed")
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*$")


def _set_from_h1(header: str) -> str | None:
    """Devuelve el set si el H1 es una sección de cartas de un set, si no None."""
    low = header.lower()
    if "card" not in low:
        return None
    for word in _SET_WORDS:
        if word in low:
            return word
    return None


def _strip_fences(lines: list[str]) -> str:
    """Une líneas quitando fences ```text y colapsando blancos de borde."""
    kept = [ln for ln in lines if not _FENCE_RE.match(ln.strip())]
    text = "\n".join(kept).strip()
    # Colapsar 3+ saltos en 2
    return re.sub(r"\n{3,}", "\n\n", text)


def parse_errata_doc(text: str, default_set: str) -> list[dict]:
    """Extrae cartas de un doc de errata.

    Returns lista de {card, set, new_text, old_text}. Solo incluye secciones H2
    que tengan un "### New Text" (descarta intros como "## Overview").
    """
    lines = text.splitlines()
    current_set = default_set
    cards: list[dict] = []

    current_card: dict | None = None
    capture: str | None = None  # "new" | "old" | None
    buf: list[str] = []

    def flush_capture():
        nonlocal capture, buf
        if current_card is not None and capture is not None and buf:
            current_card[f"{capture}_text"] = _strip_fences(buf)
        capture = None
        buf = []

    def close_card():
        nonlocal current_card
        flush_capture()
        if current_card is not None and current_card.get("new_text"):
            cards.append(current_card)
        current_card = None

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("# ") and not stripped.startswith("## "):
            close_card()
            detected = _set_from_h1(stripped[2:].strip())
            if detected:
                current_set = detected
            continue

        if stripped.startswith("## "):
            close_card()
            current_card = {
                "card": stripped[3:].strip(),
                "set": current_set,
                "new_text": None,
                "old_text": None,
            }
            continue

        if stripped.startswith("### "):
            flush_capture()
            head = stripped[4:].strip().lower()
            if head.startswith("new text"):
                capture = "new"
            elif head.startswith("old text"):
                capture = "old"
            else:
                capture = None
            continue

        if capture is not None:
            buf.append(line)

    close_card()
    return cards


def render_errata_md(cards: list[dict], set_name: str) -> str:
    """Render de las cartas de un set a Markdown. New Text como cuerpo vigente."""
    title = set_name.capitalize()
    out: list[str] = [f"# Errata — {title}", ""]
    for c in cards:
        out.append(f"## {c['card']}")
        out.append("")
        out.append("**Texto vigente:**")
        out.append("")
        out.append(c["new_text"])
        out.append("")
        if c.get("old_text"):
            out.append("> Texto anterior (reemplazado):")
            out.append(">")
            for ln in c["old_text"].splitlines():
                out.append(f"> {ln}" if ln.strip() else ">")
            out.append("")
        out.append("---")
        out.append("")
    return "\n".join(out).strip() + "\n"


# Mapeo de archivo fuente → (default_set, fecha) para consolidación con precedencia.
SOURCE_DOCS = {
    "errata_origins": {"default_set": "origins", "date": "2025-10-27"},
    "errata_spiritforged": {"default_set": "spiritforged", "date": "2026-01-13"},
    "errata_unleashed": {"default_set": "unleashed", "date": "2026-04-02"},
}


if __name__ == "__main__":
    import sys

    src = Path(sys.argv[1])
    default_set = sys.argv[2] if len(sys.argv) > 2 else "core"
    text = src.read_text(encoding="utf-8")
    cards = parse_errata_doc(text, default_set=default_set)
    by_set: dict[str, list[dict]] = {}
    for c in cards:
        by_set.setdefault(c["set"], []).append(c)
    for s, cs in by_set.items():
        print(f"{s}: {len(cs)} cartas")
