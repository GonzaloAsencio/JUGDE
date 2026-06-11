"""Consistency tests between the SQL migrations and the code that queries the DB.

These tests are the guardrail: they fail the moment a migration drifts from what
the application code actually relies on. A dead index (config mismatch) passes
every functional test on a small corpus, so only a static cross-check catches it.
"""
import pathlib
import re

BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
INGEST_PY = BACKEND_DIR / "scripts" / "ingest.py"


def _migration_files() -> list[pathlib.Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _statements() -> list[str]:
    """All migration statements, in file then in-file order."""
    stmts: list[str] = []
    for path in _migration_files():
        text = path.read_text(encoding="utf-8")
        # strip line comments so they don't shadow real statements
        text = re.sub(r"--[^\n]*", "", text)
        stmts.extend(s.strip() for s in text.split(";") if s.strip())
    return stmts


_CREATE_FTS_RE = re.compile(
    r"CREATE\s+INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)\b.*?"
    r"gin\s*\(\s*to_tsvector\(\s*'(\w+)'\s*,\s*content\s*\)\s*\)",
    re.IGNORECASE | re.DOTALL,
)
_DROP_INDEX_RE = re.compile(
    r"DROP\s+INDEX(?:\s+IF\s+EXISTS)?\s+(\w+)",
    re.IGNORECASE,
)


def _live_fts_indexes() -> dict[str, str]:
    """Replay migrations in order; return {index_name: regconfig} for the FTS
    GIN indexes on `content` that remain live after all migrations."""
    live: dict[str, str] = {}
    for stmt in _statements():
        create = _CREATE_FTS_RE.search(stmt)
        if create:
            live[create.group(1)] = create.group(2).lower()
            continue
        drop = _DROP_INDEX_RE.search(stmt)
        if drop:
            live.pop(drop.group(1), None)
    return live


def _fts_sql_regconfig() -> str:
    """The regconfig the application's FTS query actually uses."""
    from app.rag import retrieval
    m = re.search(r"to_tsvector\(\s*'(\w+)'\s*,\s*content\s*\)", retrieval._FTS_SQL)
    assert m, "could not find to_tsvector(...) in _FTS_SQL"
    return m.group(1).lower()


def test_a_live_fts_index_exists():
    """After all migrations there must be at least one live FTS index on content."""
    assert _live_fts_indexes(), "no live GIN to_tsvector index on `content` remains"


def test_fts_index_config_matches_query():
    """The live FTS index regconfig MUST match what _FTS_SQL queries with — otherwise
    Postgres silently never uses the index (the query is on a different config)."""
    query_cfg = _fts_sql_regconfig()
    live = _live_fts_indexes()
    for name, cfg in live.items():
        assert cfg == query_cfg, (
            f"FTS index {name} uses to_tsvector('{cfg}', ...) but _FTS_SQL queries "
            f"with '{query_cfg}'. The index will never be used."
        )


# ---------------------------------------------------------------------------
# source_type CHECK constraint consistency
# ---------------------------------------------------------------------------

_CHECK_RE = re.compile(
    r"CHECK\s*\(\s*source_type\s+IN\s*\(([^)]*)\)",
    re.IGNORECASE,
)
_INGEST_SOURCE_RE = re.compile(
    r'\(\s*["\'][^"\']+\.md["\']\s*,\s*["\'](\w+)["\']\s*\)',
)


def _effective_source_type_check() -> set[str]:
    """The source_type set allowed by the LAST CHECK constraint across migrations
    (replayed in order — a later migration that re-adds the constraint wins)."""
    last: str | None = None
    for stmt in _statements():
        m = _CHECK_RE.search(stmt)
        if m:
            last = m.group(1)
    assert last is not None, "no source_type CHECK constraint found in migrations"
    return {tok.strip().strip("'\"") for tok in last.split(",") if tok.strip()}


def _ingested_source_types() -> set[str]:
    """The source_type values the ingest pipeline actually writes (parsed as text,
    so the test doesn't import pymupdf-laden script modules)."""
    text = INGEST_PY.read_text(encoding="utf-8")
    return set(_INGEST_SOURCE_RE.findall(text))


def test_ingested_source_types_are_non_empty():
    """Sanity: we can actually read the ingest source_type contract."""
    assert _ingested_source_types(), "could not parse any source_type from ingest.py SOURCES"


def test_migration_check_allows_every_ingested_source_type():
    """Every source_type the ingest writes MUST be allowed by the migration CHECK —
    otherwise a fresh DB built from migrations rejects the corpus the code produces."""
    allowed = _effective_source_type_check()
    ingested = _ingested_source_types()
    missing = ingested - allowed
    assert not missing, (
        f"ingest.py writes source_type(s) {sorted(missing)} that the migration CHECK "
        f"constraint rejects (allows {sorted(allowed)}). A fresh DB would fail to ingest."
    )
