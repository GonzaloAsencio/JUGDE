"""
Convierte patch notes scrapeadas de riftbound.com a Markdown estructurado.

Formato esperado del raw (por artículo):
  CARD GALLERY / NEWS / ... (nav items)
  <Título del artículo>
  Rules and Releases
  <fecha>
  <cuerpo con secciones y cambios>
  Related Articles
  <footer>
"""
import re
from pathlib import Path

_NAV_LINES = frozenset([
    "CARD GALLERY", "NEWS", "FIND A STORE", "EVENTS",
    "How to Play", "Rules Hub", "Support", "SapoPlayer",
])

_CHANGE_PREFIXES = (
    "NEW RULE:", "NEW SYSTEM:", "CLARIFIED:", "REMOVAL:",
    "EDIT:", "NEW:", "CLARIFIED:", "ADDED:",
)

_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def _strip_nav_and_footer(text: str) -> list[str]:
    lines = text.split("\n")
    result: list[str] = []
    in_footer = False
    for line in lines:
        stripped = line.strip()
        if stripped == "Related Articles":
            in_footer = True
        if in_footer or stripped in _NAV_LINES:
            continue
        result.append(line)
    return result


def _split_articles(raw: str) -> list[str]:
    parts = re.split(r"(?=CARD GALLERY)", raw)
    return [p for p in parts if p.strip()]


def _to_markdown_body(lines: list[str]) -> str:
    """Detect section headers and add ## markers."""
    result: list[str] = []
    n = len(lines)

    for i, line in enumerate(lines):
        stripped = line.strip()

        if not stripped:
            result.append("")
            continue

        is_change = any(stripped.startswith(p) for p in _CHANGE_PREFIXES)
        prev_blank = i == 0 or not lines[i - 1].strip()

        is_section = (
            not is_change
            and prev_blank
            and len(stripped) < 90
            and stripped[0].isupper()
            and len(stripped.split()) <= 14
            and not stripped.endswith(".")
            and not _DATE_RE.match(stripped)
            and stripped != "Rules and Releases"
        )

        if is_section:
            result.append(f"## {stripped}")
        else:
            result.append(line)

    return "\n".join(result)


def _parse_article(raw_article: str) -> str | None:
    clean = _strip_nav_and_footer(raw_article)

    # Find article title (first line starting with "Riftbound")
    title_idx = None
    for i, line in enumerate(clean):
        if line.strip().startswith("Riftbound"):
            title_idx = i
            break
    if title_idx is None:
        return None

    title = clean[title_idx].strip()

    # Skip "Rules and Releases" + date line after title
    start = title_idx + 1
    while start < len(clean):
        s = clean[start].strip()
        if s in ("Rules and Releases", "") or _DATE_RE.match(s):
            start += 1
        else:
            break

    body_lines = clean[start:]
    body_md = _to_markdown_body(body_lines)

    return f"# {title}\n\n{body_md}"


def parse_patch_notes(input_path: str | Path) -> str:
    raw = Path(input_path).read_text(encoding="utf-8")
    articles = _split_articles(raw)

    parsed = []
    for article in articles:
        result = _parse_article(article)
        if result:
            parsed.append(result)

    return "\n\n---\n\n".join(parsed)


if __name__ == "__main__":
    raw = Path("data/raw/patch_notes.txt")
    out = Path("data/processed/patch_notes.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    content = parse_patch_notes(raw)
    out.write_text(content, encoding="utf-8")
    print(f"Generado: {out} ({len(content)} chars)")
