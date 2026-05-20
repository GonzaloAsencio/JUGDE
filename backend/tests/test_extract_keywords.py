"""Unit tests for extract_keywords script."""
from scripts.extract_keywords import extract_keywords

_SAMPLE = """
# Riftbound Core Rules

801. A Keyword is a specific term.

804. Keyword Glossary

805. Accelerate
805.1. Accelerate is a Unit ability.
805.1.a. Accelerate is functionally short for paying extra cost.

806. Action
806.1. Action is a Permissive keyword.

900. Some other rule
"""


def test_extract_keywords_has_h1_title():
    output = extract_keywords(_SAMPLE)
    assert "# Riftbound Keywords Reference" in output


def test_extract_keywords_creates_h2_per_keyword():
    output = extract_keywords(_SAMPLE)
    assert "## Accelerate" in output
    assert "## Action" in output


def test_extract_keywords_excludes_non_keyword_rules():
    output = extract_keywords(_SAMPLE)
    assert "801." not in output
    assert "804." not in output
    assert "900." not in output


def test_extract_keywords_content_under_correct_h2():
    output = extract_keywords(_SAMPLE)
    acc_pos = output.index("## Accelerate")
    act_pos = output.index("## Action")
    sub_pos = output.index("805.1.")
    assert acc_pos < sub_pos < act_pos
