"""Unit tests for rule-code extraction from chunk content."""
from app.rag.rules import extract_rule_codes


def test_extracts_section_header_and_inline_rules():
    text = "### 140. Units\n140. A unit is a game object.\n143. Combat begins."
    codes = extract_rule_codes(text)
    assert "140" in codes
    assert "143" in codes


def test_extracts_dotted_subrules():
    text = "103.2.b You may include up to 3 copies. See also 146.1."
    codes = extract_rule_codes(text)
    assert "103.2.b" in codes
    assert "146.1" in codes


def test_ignores_four_digit_numbers_like_dates_and_dims():
    # 2026 (year) and 1024 (dims) are not 3-digit rule codes
    text = "Last Updated 2026-03. Embeddings are 1024 dimensions."
    codes = extract_rule_codes(text)
    assert "2026" not in codes
    assert "1024" not in codes
    assert "202" not in codes


def test_empty_text_returns_empty_set():
    assert extract_rule_codes("") == set()


def test_returns_a_set_of_strings():
    codes = extract_rule_codes("002 Golden Rule and 050 Silver Rule.")
    assert codes == {"002", "050"}
