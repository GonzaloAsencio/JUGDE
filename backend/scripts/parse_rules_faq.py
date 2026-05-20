"""
Parsea el FAQ oficial de reglas de Riftbound (Unleashed) desde la URL oficial.

El contenido está en __NEXT_DATA__ JSON (Next.js SSR), en blades de tipo
articleRichText. No hace falta Selenium — el HTML viene en el payload inicial.

Chunking:
  - Blade "Revised and Clarified Rulings": 1 chunk por H2 (+ intro como chunk 0)
  - Blade "Frequently Asked Questions": 1 chunk por Q&A (bold-question paragraph)

Salida: data/processed/rules_faq.md
"""
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

_SOURCE_URL = (
    "https://riftbound.leagueoflegends.com/en-us/news/rules-and-releases"
    "/unleashed-rules-faq-and-clarifications/"
)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RiftboundJudgeBot/1.0)"}


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_blades(source: str | Path) -> list[dict]:
    """Return articleRichText blades from the page."""
    path = Path(str(source))
    if path.exists():
        html = path.read_text(encoding="utf-8")
    else:
        resp = requests.get(str(source), timeout=30, headers=_HEADERS)
        resp.raise_for_status()
        html = resp.text

    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        raise ValueError("__NEXT_DATA__ not found — page structure may have changed")

    data = json.loads(m.group(1))
    blades = data["props"]["pageProps"]["page"]["blades"]
    return [b for b in blades if b.get("type") == "articleRichText"]


# ---------------------------------------------------------------------------
# HTML → Markdown conversion
# ---------------------------------------------------------------------------

def _inline(tag: Tag) -> str:
    """Render inline content preserving bold/italic marks."""
    parts = []
    for child in tag.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            name = child.name
            text = _inline(child)
            if name in ("strong", "b"):
                parts.append(f"**{text}**")
            elif name in ("em", "i"):
                parts.append(f"*{text}*")
            elif name == "a":
                parts.append(text)
            else:
                parts.append(text)
    # Collapse non-breaking spaces and normalize
    return re.sub(r"[\xa0 ]+", " ", "".join(parts)).strip()


def _table_to_md(table: Tag) -> str:
    """Render a <table> to Markdown.

    Two patterns:
      1. Before/After comparison: 2 columns, first row is header row
      2. Rule citation: 2 columns, left = rule number, right = rule text
    """
    rows = table.find_all("tr")
    if not rows:
        return ""

    cells_per_row = [r.find_all(["td", "th"]) for r in rows]

    # Pattern: rule citation (left col is short rule number)
    if len(cells_per_row[0]) == 2:
        first_left = cells_per_row[0][0].get_text(strip=True)
        if re.match(r"^\d{3,}", first_left):
            lines = []
            for row_cells in cells_per_row:
                if len(row_cells) == 2:
                    num = row_cells[0].get_text(strip=True)
                    text = row_cells[1].get_text(separator=" ", strip=True)
                    lines.append(f"> **{num}** {text}")
            return "\n".join(lines)

    # Pattern: Before/After or generic table → Markdown table
    md_rows = []
    for i, row_cells in enumerate(cells_per_row):
        cols = [_inline(cell) if isinstance(cell, Tag) else cell.get_text(strip=True)
                for cell in row_cells]
        md_rows.append("| " + " | ".join(cols) + " |")
        if i == 0:
            md_rows.append("| " + " | ".join("---" for _ in row_cells) + " |")
    return "\n".join(md_rows)


def _el_to_lines(el: Tag) -> list[str]:
    """Convert one block element to markdown lines."""
    name = el.name
    if not name or name in ("meta", "script", "style"):
        return []

    if name in ("h1", "h2", "h3", "h4"):
        level = int(name[1])
        return [f"{'#' * level} {el.get_text(strip=True)}", ""]

    if name == "p":
        # Skip empty / meta-only paragraphs
        text = _inline(el)
        if not text:
            return []
        return [text, ""]

    if name in ("ul", "ol"):
        lines = []
        for li in el.find_all("li", recursive=False):
            bullet = "- " if name == "ul" else "1. "
            lines.append(bullet + _inline(li))
        lines.append("")
        return lines

    if name == "blockquote":
        inner = el.get_text(separator="\n", strip=True)
        return ["\n".join(f"> {l}" for l in inner.splitlines()), ""]

    if name == "div":
        # Likely a rule-citation div wrapping a <figure class="table">
        table = el.find("table")
        if table:
            return [_table_to_md(table), ""]
        # Fall through to inner text
        text = el.get_text(separator=" ", strip=True)
        return [text, ""] if text else []

    if name == "figure":
        table = el.find("table")
        if table:
            return [_table_to_md(table), ""]
        return []

    return []


def _elements_to_md(elements: list[Tag]) -> str:
    lines: list[str] = []
    for el in elements:
        lines.extend(_el_to_lines(el))
    md = "\n".join(lines)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


# ---------------------------------------------------------------------------
# Chunk splitting
# ---------------------------------------------------------------------------

def _is_standalone_bold(p: Tag) -> bool:
    """True if <p> is ONLY a single <strong>/<b> child (= FAQ question header)."""
    if p.name != "p":
        return False
    children = [c for c in p.children
                if not (isinstance(c, NavigableString) and not str(c).strip())]
    return (
        len(children) == 1
        and isinstance(children[0], Tag)
        and children[0].name in ("strong", "b")
    )


def _split_by_h2(elements: list[Tag], section_title: str) -> list[str]:
    """Split a list of elements at H2 boundaries. Returns markdown chunks."""
    chunks: list[str] = []
    current: list[Tag] = []

    def flush(acc: list[Tag]) -> None:
        md = _elements_to_md(acc)
        if md:
            chunks.append(md)

    for el in elements:
        if el.name == "h2" and current:
            flush(current)
            current = []
        current.append(el)

    flush(current)
    return chunks


def _split_by_question(elements: list[Tag]) -> list[str]:
    """Split FAQ elements at bold-question boundaries. Returns markdown chunks."""
    chunks: list[str] = []
    current: list[Tag] = []

    def flush(acc: list[Tag]) -> None:
        md = _elements_to_md(acc)
        if md:
            chunks.append(md)

    for el in elements:
        if _is_standalone_bold(el) and current:
            flush(current)
            current = []
        current.append(el)

    flush(current)
    return chunks


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_rules_faq(source: str | Path = _SOURCE_URL) -> str:
    rich_blades = _fetch_blades(source)

    all_chunks: list[str] = [
        "# Unleashed Rules FAQ and Clarifications\n\n"
        "*Source: Official Riftbound rules site — Unleashed release*"
    ]

    for i, blade in enumerate(rich_blades):
        body_html = blade.get("richText", {}).get("body", "")
        if not body_html:
            continue

        soup = BeautifulSoup(body_html, "html.parser")
        elements = [el for el in soup.find_all(True, recursive=False)
                    if isinstance(el, Tag) and el.name not in ("meta",)]

        # Heuristic: blade with H2 headers → clarification section (split by H2)
        # Blade without H2s → FAQ section (split by bold question)
        has_h2 = any(el.name == "h2" for el in elements)

        if has_h2:
            chunks = _split_by_h2(elements, "Revised and Clarified Rulings")
        else:
            chunks = _split_by_question(elements)

        all_chunks.extend(chunks)

    return "\n\n---\n\n".join(all_chunks)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    source = sys.argv[1] if len(sys.argv) > 1 else _SOURCE_URL
    out_path = Path("data/processed/rules_faq.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Fetching/parsing: {source}")
    result = parse_rules_faq(source)
    out_path.write_text(result, encoding="utf-8")
    chunk_count = result.count("---") + 1
    print(f"Generado: {out_path} ({len(result):,} chars, ~{chunk_count} chunks)")
