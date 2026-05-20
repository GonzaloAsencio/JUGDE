"""
Convierte el PDF del reglamento de Riftbound a Markdown estructurado.

Detecta headers por tamaño de fuente relativo al body text:
  - > 2.0x body → H1 (título principal)
  - > 1.4x body → H2 (sección)
  - > 1.2x body → H3 (subsección)
  - else        → párrafo
"""
import re

import pymupdf
from pathlib import Path
from statistics import mode

_RULE_BOUNDARY = re.compile(r"^\d{3,}\.")


def _extract_spans(doc: pymupdf.Document) -> list[dict]:
    spans = []
    for page in doc:
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if block["type"] != 0:  # solo bloques de texto
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if text:
                        spans.append({"text": text, "size": round(span["size"], 1)})
    return spans


def _detect_body_size(spans: list[dict]) -> float:
    sizes = [s["size"] for s in spans]
    try:
        return mode(sizes)
    except Exception:
        return min(sizes)


def _classify(size: float, body_size: float) -> str:
    ratio = size / body_size
    if ratio > 2.0:
        return "h1"
    if ratio > 1.4:
        return "h2"
    if ratio > 1.2:
        return "h3"
    return "body"


def _spans_to_markdown(spans: list[dict], body_size: float) -> str:
    lines: list[str] = []
    current_body: list[str] = []

    def flush_body():
        if current_body:
            lines.append(" ".join(current_body))
            lines.append("")
            current_body.clear()

    for span in spans:
        kind = _classify(span["size"], body_size)
        if kind == "body":
            if current_body and _RULE_BOUNDARY.match(span["text"]):
                flush_body()
            current_body.append(span["text"])
        else:
            flush_body()
            prefix = {"h1": "#", "h2": "##", "h3": "###"}[kind]
            lines.append(f"{prefix} {span['text']}")
            lines.append("")

    flush_body()

    # Colapsar líneas en blanco múltiples
    result: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank

    return "\n".join(result).strip()


def parse_rulebook(pdf_path: str | Path) -> str:
    doc = pymupdf.open(str(pdf_path))
    spans = _extract_spans(doc)
    body_size = _detect_body_size(spans)
    return _spans_to_markdown(spans, body_size)


if __name__ == "__main__":
    import sys

    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw/rulebook.pdf")
    output = Path("data/processed/rulebook.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = parse_rulebook(pdf)
    output.write_text(result, encoding="utf-8")
    print(f"Generado: {output} ({len(result)} chars)")
