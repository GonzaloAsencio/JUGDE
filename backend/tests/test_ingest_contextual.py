"""Version-scoped chunk ids + context-line application (contextual retrieval, plan 3.8).

The id must include corpus_version: without it, ingesting a new version STOLE
every identical chunk from the previous one via ON CONFLICT (id) DO UPDATE
(v2.2.0 was left with 189 rows after the v2.2.1 ingest). content_key stays
version-independent so derived artifacts (context lines) survive re-versioning.
"""
import scripts.ingest as ingest
from scripts.ingest import _make_chunk, apply_context_lines, content_key


# ---------------------------------------------------------------------------
# Version-scoped ids
# ---------------------------------------------------------------------------

def test_same_content_different_version_different_id(monkeypatch):
    monkeypatch.setattr(ingest, "CORPUS_VERSION", "v2.2.1")
    a = _make_chunk("same content", "s", "p", "rulebook", "doc")
    monkeypatch.setattr(ingest, "CORPUS_VERSION", "v2.3.0")
    b = _make_chunk("same content", "s", "p", "rulebook", "doc")
    assert a["id"] != b["id"]


def test_content_key_is_stable_across_versions(monkeypatch):
    monkeypatch.setattr(ingest, "CORPUS_VERSION", "v2.2.1")
    a = _make_chunk("same content", "s", "p", "rulebook", "doc")
    monkeypatch.setattr(ingest, "CORPUS_VERSION", "v2.3.0")
    b = _make_chunk("same content", "s", "p", "rulebook", "doc")
    assert a["content_key"] == b["content_key"]


def test_content_key_helper_matches_chunk_field():
    chunk = _make_chunk("body", "s", "p", "rulebook", "doc")
    assert chunk["content_key"] == content_key("doc", "body")


# ---------------------------------------------------------------------------
# apply_context_lines
# ---------------------------------------------------------------------------

def _chunks():
    return [
        _make_chunk("383.3.d.1. Turn player orders triggers.", "383.", "L3", "rulebook", "rulebook"),
        _make_chunk("429.2. Add abilities finalize immediately.", "429.", "L3", "rulebook", "rulebook"),
        _make_chunk("## Vex Apathetic\ncard text", "Vex Apathetic", "cards", "card", "cards"),
    ]


def test_apply_prepends_line_only_to_mapped_chunks():
    chunks = _chunks()
    ctx = {chunks[0]["content_key"]: {"line": "Context: who resolves first."}}
    applied, missing = apply_context_lines(chunks, ctx)
    assert applied == 1
    assert chunks[0]["content"].startswith("Context: who resolves first.\n\n383.3.d.1.")
    assert chunks[1]["content"].startswith("429.2.")


def test_apply_counts_rulebook_chunks_without_line_as_missing():
    chunks = _chunks()
    ctx = {chunks[0]["content_key"]: {"line": "Context: x."}}
    _, missing = apply_context_lines(chunks, ctx)
    # chunk[1] is rulebook and unmapped; the card chunk is out of scope
    assert missing == 1


def test_apply_keeps_the_raw_content_id():
    # id stays keyed to the RAW content: re-ingesting with improved lines
    # upserts the same rows instead of duplicating the corpus version.
    chunks = _chunks()
    original_id = chunks[0]["id"]
    apply_context_lines(chunks, {chunks[0]["content_key"]: {"line": "Context: x."}})
    assert chunks[0]["id"] == original_id


def test_apply_accepts_plain_string_entries():
    chunks = _chunks()
    applied, _ = apply_context_lines(chunks, {chunks[0]["content_key"]: "Context: plain."})
    assert applied == 1
    assert chunks[0]["content"].startswith("Context: plain.\n\n")
