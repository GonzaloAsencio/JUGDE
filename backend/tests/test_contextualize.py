"""Pure logic of the context-line batch generator (contextual retrieval, plan 3.8)."""
import json

from scripts.contextualize import build_prompt, load_checkpoint, sanitize_line, save_checkpoint


# ---------------------------------------------------------------------------
# sanitize_line
# ---------------------------------------------------------------------------

def test_sanitize_collapses_to_single_prefixed_line():
    raw = "This rule explains\nwho resolves first\n\nwhen triggers collide."
    line = sanitize_line(raw)
    assert "\n" not in line
    assert line == "Context: This rule explains who resolves first when triggers collide."


def test_sanitize_does_not_double_the_prefix():
    assert sanitize_line("Context: already prefixed.") == "Context: already prefixed."


def test_sanitize_strips_rule_codes():
    # A leaked rule code would pollute rule_codes extraction at query time and
    # re-introduce paper hits through the context line.
    line = sanitize_line("See 383.3.d.1 for trigger ordering between players.")
    assert "383" not in line


def test_sanitize_strips_markdown_fences_and_quotes():
    line = sanitize_line('```\n"who resolves first when abilities collide"\n```')
    assert line == "Context: who resolves first when abilities collide."


def test_sanitize_truncates_overlong_lines():
    line = sanitize_line("word " * 200)
    assert len(line) <= 300


def test_sanitize_rejects_empty_or_trivial_output():
    assert sanitize_line("") is None
    assert sanitize_line("```\n```") is None
    assert sanitize_line("ok") is None


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------

def test_prompt_contains_chunk_and_section():
    prompt = build_prompt("383. Triggered Abilities", "383.3.d.1. Turn player orders triggers.")
    assert "383.3.d.1. Turn player orders triggers." in prompt
    assert "383. Triggered Abilities" in prompt


def test_prompt_forbids_rule_numbers_and_asks_for_one_line():
    prompt = build_prompt("sec", "content")
    low = prompt.lower()
    assert "rule number" in low
    assert "one line" in low or "single line" in low


# ---------------------------------------------------------------------------
# checkpoint
# ---------------------------------------------------------------------------

def test_checkpoint_roundtrip(tmp_path):
    path = tmp_path / "context_lines.json"
    data = {"key-1": {"line": "Context: x.", "section": "383."}}
    save_checkpoint(path, data)
    assert load_checkpoint(path) == data


def test_checkpoint_missing_file_returns_empty(tmp_path):
    assert load_checkpoint(tmp_path / "nope.json") == {}


def test_checkpoint_is_utf8_json(tmp_path):
    path = tmp_path / "context_lines.json"
    save_checkpoint(path, {"k": {"line": "Context: habilidad española."}})
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["k"]["line"] == "Context: habilidad española."
