"""Characterization tests for scripts.ingest DB paths against a real Postgres.

Pins upsert_chunks (INSERT ... ON CONFLICT DO UPDATE) and get_existing_ids so
the Phase 4 changes (execute_values batching; WHERE corpus_version on
get_existing_ids) have a net. test_get_existing_ids_returns_all_versions
documents the CURRENT cross-version behavior on purpose: Phase 4 will change it,
and updating this test is how that change stays visible instead of silent.
"""
import uuid

import pytest

from app.db import get_conn
from scripts.ingest import get_existing_ids, upsert_chunks

pytestmark = pytest.mark.integration


def _chunk(*, id=None, content="body", section="Sec", corpus_version="v1", metadata=None):
    return {
        "id": id or str(uuid.uuid4()),
        "content": content,
        "embedding": None,
        "source_type": "rulebook",
        "source_document": "doc",
        "section": section,
        "parent_section": None,
        "corpus_version": corpus_version,
        "metadata": metadata,
    }


def _count(pool, corpus_version=None):
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            if corpus_version is None:
                cur.execute("SELECT COUNT(*) FROM corpus_chunks")
            else:
                cur.execute("SELECT COUNT(*) FROM corpus_chunks WHERE corpus_version = %s", (corpus_version,))
            return cur.fetchone()[0]


def test_upsert_inserts_rows(clean_corpus):
    ch = _chunk()
    with get_conn(clean_corpus) as conn:
        upsert_chunks(conn, [ch])
    assert _count(clean_corpus) == 1


def test_upsert_on_conflict_updates_content(clean_corpus):
    cid = str(uuid.uuid4())
    with get_conn(clean_corpus) as conn:
        upsert_chunks(conn, [_chunk(id=cid, content="first")])
        upsert_chunks(conn, [_chunk(id=cid, content="second")])
    assert _count(clean_corpus) == 1  # same id -> update, not duplicate
    with get_conn(clean_corpus) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM corpus_chunks WHERE id = %s", (cid,))
            assert cur.fetchone()[0] == "second"


def test_upsert_persists_metadata(clean_corpus):
    cid = str(uuid.uuid4())
    with get_conn(clean_corpus) as conn:
        upsert_chunks(conn, [_chunk(id=cid, metadata={"tag": "accel"})])
        with conn.cursor() as cur:
            cur.execute("SELECT metadata FROM corpus_chunks WHERE id = %s", (cid,))
            assert cur.fetchone()[0] == {"tag": "accel"}


def test_get_existing_ids_sees_upserted(clean_corpus):
    cid = str(uuid.uuid4())
    with get_conn(clean_corpus) as conn:
        upsert_chunks(conn, [_chunk(id=cid, corpus_version="v1")])
        existing = get_existing_ids(conn, "v1")
    assert cid in {str(x) for x in existing}


def test_get_existing_ids_scoped_to_version(clean_corpus):
    """Phase 4b behavior: get_existing_ids is scoped to corpus_version, so a
    query for v1 sees v1's ids only — not v2's. (Was cross-version before 4b;
    changed deliberately — chunk ids are version-namespaced so this is safe.)"""
    v1, v2 = str(uuid.uuid4()), str(uuid.uuid4())
    with get_conn(clean_corpus) as conn:
        upsert_chunks(conn, [_chunk(id=v1, corpus_version="v1")])
        upsert_chunks(conn, [_chunk(id=v2, corpus_version="v2")])
        existing = {str(x) for x in get_existing_ids(conn, "v1")}
    assert v1 in existing
    assert v2 not in existing
