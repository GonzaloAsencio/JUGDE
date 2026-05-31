"""
Convierte los 11 documentos oficiales de Riftbound (en ~/Desktop por defecto)
a backend/data/processed/*.md, listos para ingest.

- Docs ya-Markdown (Core Rules, Tournament, FAQs, Patch Notes): se copian con
  nombre normalizado y encoding UTF-8.
- Erratas (3 docs): se parsean (New/Old + set por H1 interno), se consolidan por
  carta con precedencia por fecha (la más reciente gana) y se renderiza un
  errata_<set>.md por expansión.

Uso:
  python scripts/build_corpus.py [carpeta_fuente]
"""
import os
from pathlib import Path

from scripts.parse_errata import parse_errata_doc, render_errata_md

# Documentos que YA vienen en Markdown → copia directa.
# (source filename en Desktop) -> (stem de salida, default_set/etiqueta informativa)
PASSTHROUGH_DOCS = {
    "# Riftbound Core Rules.txt": "rulebook",
    "# Riftbound Tournament Rules.txt": "tournament_rules",
    "# Riftbound Core Rules Patch Notes.txt": "patch_notes_origins",
    "# Riftbound Core Rules – Spiritforged Patch Notes.txt": "patch_notes_spiritforged",
    "Riftbound Core Rules Unleashed Patch Notes.txt": "patch_notes_unleashed",
    "# Riftbound Origins FAQ.txt": "faq_origins",
    "# Riftbound FAQ – Spiritforged.txt": "faq_spiritforged",
    "# Unleashed Rules FAQ and Clarifications.txt": "faq_unleashed",
}

# Erratas: (source filename) -> (default_set, fecha ISO para precedencia)
ERRATA_DOCS = {
    "Riftbound Origins Card Errata.txt": ("origins", "2025-10-27"),
    "# Riftbound Spiritforged Errata.txt": ("spiritforged", "2026-01-13"),
    "Unleashed Errata Updates.txt": ("unleashed", "2026-04-02"),
}


def consolidate_errata(docs: list[dict]) -> dict[str, list[dict]]:
    """Consolida cartas de varios docs de errata.

    `docs`: lista de {"date": ISO, "cards": [card dicts]}.
    Si una carta aparece en varios docs, gana la de fecha MÁS RECIENTE.
    Returns: dict set -> lista de cartas (ordenada por nombre).
    """
    latest: dict[str, dict] = {}  # card name -> (date, card)
    latest_date: dict[str, str] = {}

    for doc in docs:
        date = doc["date"]
        for card in doc["cards"]:
            name = card["card"]
            if name not in latest_date or date > latest_date[name]:
                latest_date[name] = date
                latest[name] = card

    by_set: dict[str, list[dict]] = {}
    for card in latest.values():
        by_set.setdefault(card["set"], []).append(card)
    for cards in by_set.values():
        cards.sort(key=lambda c: c["card"])
    return by_set


def _normalize_md(text: str) -> str:
    """Normaliza saltos de línea y asegura newline final."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip() + "\n"


def build_corpus(source_dir: Path, processed_dir: Path) -> dict:
    processed_dir.mkdir(parents=True, exist_ok=True)
    report = {"passthrough": [], "errata": [], "missing": []}

    # 1. Passthrough docs
    for src_name, stem in PASSTHROUGH_DOCS.items():
        src = source_dir / src_name
        if not src.exists():
            report["missing"].append(src_name)
            continue
        text = _normalize_md(src.read_text(encoding="utf-8"))
        (processed_dir / f"{stem}.md").write_text(text, encoding="utf-8")
        report["passthrough"].append(stem)

    # 2. Erratas: parse + consolidate + render por set
    parsed_docs = []
    for src_name, (default_set, date) in ERRATA_DOCS.items():
        src = source_dir / src_name
        if not src.exists():
            report["missing"].append(src_name)
            continue
        cards = parse_errata_doc(src.read_text(encoding="utf-8"), default_set=default_set)
        parsed_docs.append({"date": date, "cards": cards})

    by_set = consolidate_errata(parsed_docs)
    for set_name, cards in by_set.items():
        md = render_errata_md(cards, set_name=set_name)
        (processed_dir / f"errata_{set_name}.md").write_text(md, encoding="utf-8")
        report["errata"].append({"set": set_name, "cards": len(cards)})

    return report


if __name__ == "__main__":
    import sys

    source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.path.expanduser("~")) / "Desktop"
    processed = Path(__file__).parent.parent / "data" / "processed"
    rep = build_corpus(source, processed)
    print("Passthrough:", ", ".join(rep["passthrough"]))
    print("Erratas:", rep["errata"])
    if rep["missing"]:
        print("FALTANTES:", rep["missing"])
