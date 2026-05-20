"""
Convierte el PDF de Tournament Rules de Riftbound a Markdown estructurado.
Reutiliza parse_rulebook.parse_rulebook() que detecta headers por tamaño de fuente.
"""
from pathlib import Path

from parse_rulebook import parse_rulebook


if __name__ == "__main__":
    import sys

    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw/tournament_rules.pdf")
    output = Path("data/processed/tournament_rules.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = parse_rulebook(pdf)
    output.write_text(result, encoding="utf-8")
    print(f"Generado: {output} ({len(result)} chars)")
