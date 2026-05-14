"""
Genera el fixture PDF para tests del parser.
Corre una sola vez: python scripts/create_test_fixtures.py
"""
import pymupdf
from pathlib import Path

OUTPUT = Path(__file__).parent.parent / "tests" / "fixtures" / "rulebook_sample.pdf"


def create_fixture_pdf():
    doc = pymupdf.open()

    # --- Página 1 ---
    page = doc.new_page(width=595, height=842)  # A4

    # Título principal (24pt)
    page.insert_text((72, 80), "Riftbound Core Rules", fontsize=24, fontname="helv")

    # Sección 1 (16pt)
    page.insert_text((72, 160), "1. Game Overview", fontsize=16, fontname="helv")

    # Cuerpo (10pt)
    page.insert_text(
        (72, 195),
        "Riftbound is a trading card game for two players.",
        fontsize=10,
        fontname="helv",
    )
    page.insert_text(
        (72, 210),
        "Each player builds a deck and competes to reduce the opponent's health to zero.",
        fontsize=10,
        fontname="helv",
    )

    # Subsección 1.1 (13pt)
    page.insert_text((72, 250), "1.1 The Golden Rules", fontsize=13, fontname="helv")

    page.insert_text(
        (72, 275),
        "If a card contradicts the rules, the card takes precedence.",
        fontsize=10,
        fontname="helv",
    )
    page.insert_text(
        (72, 290),
        "Impossible instructions are ignored.",
        fontsize=10,
        fontname="helv",
    )

    # Subsección 1.2 (13pt)
    page.insert_text((72, 330), "1.2 Starting the Game", fontsize=13, fontname="helv")

    page.insert_text(
        (72, 355),
        "Each player starts with 20 health points.",
        fontsize=10,
        fontname="helv",
    )
    page.insert_text(
        (72, 370),
        "Draw 5 cards to form your opening hand.",
        fontsize=10,
        fontname="helv",
    )

    # --- Página 2 ---
    page2 = doc.new_page(width=595, height=842)

    # Sección 2 (16pt)
    page2.insert_text((72, 80), "2. Card Types", fontsize=16, fontname="helv")

    page2.insert_text(
        (72, 110),
        "There are several types of cards in Riftbound.",
        fontsize=10,
        fontname="helv",
    )

    # Subsección 2.1 (13pt)
    page2.insert_text((72, 150), "2.1 Champions", fontsize=13, fontname="helv")

    page2.insert_text(
        (72, 175),
        "Champions are your main units. Each player starts with one champion.",
        fontsize=10,
        fontname="helv",
    )

    # Subsección 2.2 (13pt)
    page2.insert_text((72, 215), "2.2 Spells", fontsize=13, fontname="helv")

    page2.insert_text(
        (72, 240),
        "Spells are one-time effects played from your hand.",
        fontsize=10,
        fontname="helv",
    )

    doc.save(str(OUTPUT))
    print(f"Fixture PDF creado: {OUTPUT}")


if __name__ == "__main__":
    create_fixture_pdf()
