from pathlib import Path
from scripts.parse_rulebook import parse_rulebook

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_PDF = FIXTURES / "rulebook_sample.pdf"
EXPECTED_MD = FIXTURES / "rulebook_sample_expected.md"


def test_parse_rulebook_produces_markdown():
    result = parse_rulebook(SAMPLE_PDF)
    assert isinstance(result, str)
    assert len(result) > 0


def test_parse_rulebook_title_becomes_h1():
    result = parse_rulebook(SAMPLE_PDF)
    assert "# Riftbound Core Rules" in result


def test_parse_rulebook_sections_become_h2():
    result = parse_rulebook(SAMPLE_PDF)
    assert "## 1. Game Overview" in result
    assert "## 2. Card Types" in result


def test_parse_rulebook_subsections_become_h3():
    result = parse_rulebook(SAMPLE_PDF)
    assert "### 1.1 The Golden Rules" in result
    assert "### 1.2 Starting the Game" in result
    assert "### 2.1 Champions" in result
    assert "### 2.2 Spells" in result


def test_parse_rulebook_body_text_preserved():
    result = parse_rulebook(SAMPLE_PDF)
    assert "Each player starts with 20 health points." in result
    assert "Draw 5 cards to form your opening hand." in result


def test_parse_rulebook_matches_expected_output():
    result = parse_rulebook(SAMPLE_PDF)
    expected = EXPECTED_MD.read_text(encoding="utf-8")
    assert result.strip() == expected.strip()
