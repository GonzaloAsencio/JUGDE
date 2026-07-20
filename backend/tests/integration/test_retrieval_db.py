"""Characterization tests for the retrieval lookups against a real Postgres.

These PIN the current behavior of tagged_lookup / family_lookup — the per-tag
LIMIT 2, the dedup, the source_type ordering, corpus_version scoping — so the
Phase 4 N+1 refactor has a real net to catch any behavior drift. All prior
tagged_lookup tests mock the cursor and therefore cannot see the SQL semantics.
"""
import uuid

import pytest

from app.db import get_conn
from app.rag.retrieval import family_lookup, tagged_lookup

pytestmark = pytest.mark.integration


def _insert(cur, *, section, source_type="rulebook", corpus_version="v1", content="body"):
    cur.execute(
        "INSERT INTO corpus_chunks "
        "(id, content, source_type, source_document, section, parent_section, corpus_version, ingested_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())",
        (str(uuid.uuid4()), content, source_type, "doc", section, None, corpus_version),
    )


def _seed(pool, rows):
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            for row in rows:
                _insert(cur, **row)
        conn.commit()


# --- tagged_lookup ---------------------------------------------------------

def test_tagged_lookup_caps_at_2_per_tag(clean_corpus):
    """Current contract: at most 2 chunks PER TAG (SQL LIMIT 2). A naive
    ILIKE ANY(...) collapse would break this — hence the pin."""
    _seed(clean_corpus, [
        {"section": "Accelerate"},
        {"section": "Accelerate rules"},
        {"section": "Accelerate timing"},
    ])
    result = tagged_lookup(clean_corpus, ["accelerate"], "v1")
    assert len(result) == 2


def test_tagged_lookup_dedups_same_chunk_across_tags(clean_corpus):
    _seed(clean_corpus, [{"section": "Accelerate"}])
    result = tagged_lookup(clean_corpus, ["accel", "accelerate"], "v1")
    assert len(result) == 1


def test_tagged_lookup_card_ordered_before_rulebook(clean_corpus):
    _seed(clean_corpus, [
        {"section": "Yasuo", "source_type": "rulebook"},
        {"section": "Yasuo", "source_type": "card"},
    ])
    result = tagged_lookup(clean_corpus, ["yasuo"], "v1")
    assert [c.source_type for c in result] == ["card", "rulebook"]


def test_tagged_lookup_similarity_is_zero(clean_corpus):
    _seed(clean_corpus, [{"section": "Accelerate"}])
    result = tagged_lookup(clean_corpus, ["accelerate"], "v1")
    assert result[0].similarity == 0.0


def test_tagged_lookup_scoped_to_corpus_version(clean_corpus):
    _seed(clean_corpus, [{"section": "Accelerate", "corpus_version": "v1"}])
    assert tagged_lookup(clean_corpus, ["accelerate"], "v2") == []


def test_tagged_lookup_empty_tags_returns_empty(clean_corpus):
    assert tagged_lookup(clean_corpus, [], "v1") == []


# --- family_lookup ---------------------------------------------------------

def test_family_lookup_exact_section_only(clean_corpus):
    _seed(clean_corpus, [
        {"section": "809. Deflect"},
        {"section": "810. Other"},
    ])
    result = family_lookup(clean_corpus, ["809. Deflect"], "v1")
    assert [c.section for c in result] == ["809. Deflect"]


def test_family_lookup_returns_all_chunks_no_limit(clean_corpus):
    """Unlike tagged_lookup, family_lookup has no LIMIT — a family split across
    many chunks comes back whole."""
    _seed(clean_corpus, [{"section": "809. Deflect", "content": f"c{i}"} for i in range(5)])
    result = family_lookup(clean_corpus, ["809. Deflect"], "v1")
    assert len(result) == 5


def test_family_lookup_scoped_to_corpus_version(clean_corpus):
    _seed(clean_corpus, [{"section": "809. Deflect", "corpus_version": "v1"}])
    assert family_lookup(clean_corpus, ["809. Deflect"], "v2") == []
