"""
Convierte archivos de errata en texto plano a Markdown estructurado.

Formato de entrada:
  Card Name
  [NEW TEXT]
  <nuevo texto de la carta>
  ▲
  [OLD TEXT]
  <texto anterior>

Para el corpus solo indexamos el NEW TEXT (texto autoritativo).
El OLD TEXT se incluye como referencia pero con menor peso.
"""
import re
from pathlib import Path


def _split_entries(text: str) -> list[str]:
    """Separa el texto en entradas individuales por carta."""
    # Las entradas están separadas por líneas en blanco seguidas de un nombre de carta
    # El separador ▲ está dentro de cada entrada
    entries = re.split(r"\n(?=\S[^\n]*\n\[NEW TEXT\])", text)
    return [e.strip() for e in entries if e.strip() and "[NEW TEXT]" in e]


def _parse_entry(entry: str) -> dict | None:
    """Parsea una entrada individual y retorna sus partes."""
    parts = re.split(r"\[NEW TEXT\]|\[OLD TEXT\]|▲", entry)
    if len(parts) < 3:
        return None

    name = parts[0].strip()
    new_text = parts[1].strip()
    old_text = parts[2].strip() if len(parts) > 2 else ""

    if not name or not new_text:
        return None

    return {"name": name, "new_text": new_text, "old_text": old_text}


def _entry_to_markdown(entry: dict) -> str:
    lines = [f"## {entry['name']}", "", "**Current text:**", "", entry["new_text"]]
    if entry["old_text"]:
        lines += ["", "**Previous text:**", "", entry["old_text"]]
    return "\n".join(lines)


def parse_errata(input_path: str | Path, set_name: str) -> str:
    text = Path(input_path).read_text(encoding="utf-8")

    # Limpiar intro text antes del primer [NEW TEXT]
    first_entry = text.find("[NEW TEXT]")
    if first_entry == -1:
        return ""

    # Retroceder hasta la línea del nombre de la carta
    preamble_end = text.rfind("\n", 0, first_entry)
    text = text[preamble_end:].strip()

    entries = _split_entries(text)
    parsed = [_parse_entry(e) for e in entries]
    parsed = [p for p in parsed if p is not None]

    if not parsed:
        return ""

    header = f"# Errata — {set_name}\n\n"
    body = "\n\n---\n\n".join(_entry_to_markdown(p) for p in parsed)
    return header + body


ERRATA_FILES = [
    ("errata_origins.txt", "Origins"),
    ("errata_spiritforged.txt", "Spiritforged"),
    ("errata_unleashed.txt", "Unleashed"),
]

if __name__ == "__main__":
    raw_dir = Path("data/raw")
    processed_dir = Path("data/processed")
    processed_dir.mkdir(parents=True, exist_ok=True)

    all_errata: list[str] = []
    for filename, set_name in ERRATA_FILES:
        path = raw_dir / filename
        if not path.exists():
            print(f"Skipping {filename} (not found)")
            continue
        result = parse_errata(path, set_name)
        if result:
            all_errata.append(result)
            print(f"Parsed {filename}: {len(result)} chars")

    if all_errata:
        output = "\n\n---\n\n".join(all_errata)
        out_path = processed_dir / "errata.md"
        out_path.write_text(output, encoding="utf-8")
        print(f"Generado: {out_path} ({len(output)} chars)")
