from pathlib import Path
from scripts.parse_rulebook import parse_rulebook, _spans_to_markdown

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


# ---------------------------------------------------------------------------
# _spans_to_markdown — rule boundary splitting
# ---------------------------------------------------------------------------

def _body_span(text: str, size: float = 10.0) -> dict:
    return {"text": text, "size": size}


def test_spans_to_markdown_splits_rules_into_separate_paragraphs():
    spans = [
        _body_span("805. Accelerate (Action): blah blah blah."),
        _body_span("806. Ambush (Passive): blah blah blah."),
        _body_span("807. Armor N (Passive): blah blah blah."),
    ]
    result = _spans_to_markdown(spans, body_size=10.0)
    paragraphs = [p for p in result.split("\n\n") if p.strip()]
    assert len(paragraphs) == 3


def test_spans_to_markdown_non_rule_body_merges():
    spans = [
        _body_span("This is a sentence."),
        _body_span("This continues the same paragraph."),
    ]
    result = _spans_to_markdown(spans, body_size=10.0)
    paragraphs = [p for p in result.split("\n\n") if p.strip()]
    assert len(paragraphs) == 1


def test_spans_to_markdown_rule_content_is_preserved():
    spans = [
        _body_span("805. Accelerate (Action): Move this unit."),
        _body_span("806. Ambush (Passive): React to attack."),
    ]
    result = _spans_to_markdown(spans, body_size=10.0)
    assert "805. Accelerate" in result
    assert "806. Ambush" in result
