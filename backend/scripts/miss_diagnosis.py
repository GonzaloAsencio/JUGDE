"""Miss diagnosis — drill into every gold ref that never reaches the context
production ACTUALLY builds, WITHOUT an LLM (embedder + DB only).

The unit of diagnosis is the MISSING REF, not the question: diagnose() used to
skip any question where ANY ref was retrieved, hiding every partial-coverage gap
(eval-020 has 816 at rank 1 and 383.3.d nowhere, and looked healthy).

Selection: a ref is a miss when it is absent from the real generation context
(routed -> the stuffed rulebook; otherwise -> _retrieve's assembly). NOT from
the top-15 — that is only the diagnostic LENS below.

For each miss it dumps three things and a verdict:
  1. the gold ref(s) and the corpus chunk(s) that actually cover them (proof the
     rule IS in the corpus — this is a retrieval gap, not a corpus gap),
  2. the top-15 vector results actually retrieved (rank, source, section, codes),
  3. a deterministic class:
       (C) ranking — the top-15 lens DOES cover the ref: the embedding can reach
           it, it just didn't survive into the context (which ships top_k=5).
       (A) granularity — a SIBLING of the gold rule (same 3-digit base, e.g.
           ``383.4.d`` for gold ``383.4.e``) is retrieved but nothing covers it →
           the sub-rule chunk got separated from its retrievable context.
       (B) semantic gap — nothing from the gold's rule family is retrieved → the
           question's vocabulary is too far from the rule text.
  Note: a chunk listing ``383`` or ``383.4`` already COVERS ``383.4.e`` (lineage),
  so class (A) is strictly siblings/cousins that cover nothing.

This class decides the lever (ranking vs chunk lineage vs FTS-keyword/vocabulary)
with NO LLM call.

Usage (from backend/):
    python -m scripts.miss_diagnosis

Requires DATABASE_URL + ingested corpus. Never SPENDS Gemini quota, but the key
must be PRESENT — Settings() fails closed without it. Zero quota, not zero config.
"""
import re
import sys

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, get_conn, init_pool
from app.rag.embedder import Embedder
from app.rag.retrieval import vector_search
from app.rag.rules import extract_rule_codes
from scripts.eval_judge import _parse_refs
from scripts.retrieval_probe import (
    _NoHydeProvider,
    _load_evaluable,
    _resolve_corpus_version,
    chunk_covers_refs,
    per_ref_ranks,
    resolve_production_context,
)

TOP_K = 15
_BASE = re.compile(r"\d{3}")


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_miss_diagnosis.py — no DB, no network)
# ---------------------------------------------------------------------------

def numeric_base(code: str) -> str | None:
    """3-digit base of a rule code: ``383.4.e`` -> ``383``. None for non-numeric
    (e.g. ``errata/...``)."""
    m = _BASE.match(code)
    return m.group(0) if m else None


def missing_refs(per_ref: dict[str, int | None]) -> list[str]:
    """The gold refs that never reached the context, in declared order.

    The diagnosis unit is the MISSING REF, not the question. diagnose() used to
    skip any question where first_covering_rank found ANY ref, so eval-020 (816
    at rank 1, 383.3.d nowhere) and eval-030 (809.1 at rank 12, 365.1 nowhere)
    were never diagnosed at all — the two partial-coverage gaps were invisible
    to the tool whose entire job is choosing their lever.
    """
    return [ref for ref, rank in per_ref.items() if rank is None]


def classify_miss(refs: list[str], top_chunks) -> str:
    """Classify a miss as ``C:ranking``, ``A:granularity`` or ``B:semantic_gap``.

    Ranking (C): *top_chunks* actually COVERS the ref — the rule is reachable by
    the embedding, it just didn't survive into the production context (which
    ships top_k=5 against this top-15 lens). The lever is ranking, not chunking.
    Granularity (A): a chunk lists a rule sharing the gold's 3-digit base (same
    family) but none covers it — the sub-rule chunk got separated from its
    retrievable context. Semantic gap (B): nothing from the gold's family is
    present — the question's vocabulary is too far from the rule text.

    C is checked FIRST and exists because this function used to carry the
    precondition "*top_chunks* must be a genuine miss" — which the caller
    guaranteed by filtering on first_covering_rank. That filter was removed (it
    hid partial-coverage gaps) and the precondition went unenforced: absence is
    judged against the production context, coverage against this wider lens, so
    a gold at rank 12 reached here and A fired off the gold ITSELF instead of a
    sibling. A classifier with an unenforced precondition is a trap; this one is
    total.
    """
    gold_bases = {b for ref in refs if (b := numeric_base(ref)) is not None}
    if not gold_bases:
        return "B:semantic_gap"
    for chunk in top_chunks:
        codes = extract_rule_codes(chunk.content)
        if chunk_covers_refs(refs, codes, getattr(chunk, "source_type", "rulebook")):
            return "C:ranking"
    for chunk in top_chunks:
        for code in extract_rule_codes(chunk.content):
            if numeric_base(code) in gold_bases:
                return "A:granularity"
    return "B:semantic_gap"


# ---------------------------------------------------------------------------
# DB-driven diagnosis (manual run — not unit-tested)
# ---------------------------------------------------------------------------

def _load_all_chunks(pool, corpus_version):
    """Every (content, section, source_type) for the active corpus — used to
    locate the chunk that covers a gold ref, proving the rule is ingested."""
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content, section, source_type FROM corpus_chunks "
                "WHERE corpus_version = %s",
                (corpus_version,),
            )
            return cur.fetchall()


def _covering_chunks(refs, all_chunks):
    """Corpus rows (content, section, source_type) whose codes cover the refs."""
    hits = []
    for content, section, source_type in all_chunks:
        codes = extract_rule_codes(content)
        if chunk_covers_refs(refs, codes, source_type):
            hits.append((content, section, source_type, sorted(codes)))
    return hits


def _print_top15(chunks) -> None:
    for rank, c in enumerate(chunks, 1):
        codes = sorted(extract_rule_codes(c.content))
        codes_str = ", ".join(codes[:8]) + (" …" if len(codes) > 8 else "")
        print(f"    [{rank:2d}] {c.source_type:10s} sim={c.similarity:.3f} "
              f"section={c.section!r}")
        print(f"         codes: {codes_str or '(none)'}")


def diagnose(questions, embedder, pool, corpus_version, all_chunks, settings) -> list[dict]:
    """One record per MISSING REF, judged against the real generation context.

    Two fixes over the previous version, both of the same family of bug:
      * it filtered on first_covering_rank (ANY ref) and skipped questions where
        one ref happened to be retrieved — hiding every partial-coverage gap;
      * it filtered on the raw vector arm, not the context production builds,
        so routed questions and family-completed refs looked like misses.
    The vector top-15 is still dumped as the diagnostic lens: it answers WHY a
    ref is unreachable, which is what picks the lever.
    """
    provider = _NoHydeProvider()
    routing_enabled = settings.hard_query_routing
    misses = []
    for q in questions:
        refs = _parse_refs(q["rule_reference"])
        question = q["question"]

        # An unparseable rule_reference yields refs=[] -> per_ref_ranks {} ->
        # missing_refs [] -> the question would be skipped below as if every
        # gold ref had reached the model. missing_refs is right ("none are
        # missing"); silently reading that as coverage is not. Say so instead.
        if not refs:
            print(f"WARNING: {q.get('id', '?')} has an unparseable rule_reference "
                  f"({q['rule_reference']!r}) — NOT diagnosed, not evidence of coverage.",
                  file=sys.stderr)
            continue

        resolved = resolve_production_context(
            question, embedder, pool, provider, settings, corpus_version, "diag",
            routing_enabled=routing_enabled,
        )

        absent = missing_refs(per_ref_ranks(refs, resolved.chunks))
        if not absent:
            continue  # every gold ref reached the model — nothing to diagnose

        # The lens: what the embedding CAN reach, which decides the lever.
        top = vector_search(pool, resolved.embedding, corpus_version, top_k=TOP_K)
        for ref in absent:
            misses.append({
                "id": q.get("id", "?"),
                "question": question,
                "ref": ref,
                "rule_reference": q["rule_reference"],
                "routed": resolved.routed,
                "stuffing_unavailable": resolved.stuffing_unavailable,
                "top": top,
                # Classified per-ref: a sibling of ANOTHER gold ref must not
                # rescue this one's verdict.
                "class": classify_miss([ref], top),
                "covering": _covering_chunks([ref], all_chunks),
            })
    return misses


def _print_report(misses) -> None:
    print("\n" + "=" * 72)
    print("MISS DIAGNOSIS (deterministic — no LLM, per MISSING REF)")
    print("=" * 72)
    questions = {m["id"] for m in misses}
    print(f"  missing refs: {len(misses)}  across {len(questions)} questions\n")

    # build_stuffed_chunks is never-raise: a missing/corrupt rulebook.md sends a
    # question that should have routed down the RAG path. Saying nothing would
    # let a 5-chunk measurement masquerade as "not even the full rulebook has it".
    degraded = sorted({m["id"] for m in misses if m["stuffing_unavailable"]})
    if degraded:
        print(f"  *** WARNING: stuffing UNAVAILABLE for {len(degraded)} question(s) "
              f"that should have routed.")
        print("      build_stuffed_chunks returned None (missing/corrupt "
              "data/processed/rulebook.md?).")
        print("      Their refs were judged against the RAG context, NOT the full "
              "rulebook — do not read these as corpus gaps.")
        print(f"      Affected: {', '.join(degraded)}\n")

    a = sum(1 for m in misses if m["class"].startswith("A"))
    b = sum(1 for m in misses if m["class"].startswith("B"))
    print(f"  (A) granularity  : {a}  -> lever: chunk lineage")
    print(f"  (B) semantic gap : {b}  -> lever: FTS-keyword arm\n")
    print("  Per missing ref:")
    for m in misses:
        corpus = "in corpus" if m["covering"] else "NOT IN CORPUS"
        print(f"    {m['id']:10s} ref={m['ref']:<12s} {m['class']:16s} "
              f"gold chunk {corpus}")
    print()

    for m in misses:
        print("-" * 72)
        print(f"  {m['id']}  MISSING ref={m['ref']}  (gold set: {m['rule_reference']})"
              f"  CLASS={m['class']}")
        print(f"  Q: {m['question']}")
        cov = m["covering"]
        print(f"\n  Gold chunk(s) in corpus that cover the ref: {len(cov)}")
        for content, section, source_type, codes in cov[:3]:
            preview = content.replace("\n", " ")[:160]
            print(f"    - {source_type:10s} section={section!r}")
            print(f"      codes: {', '.join(codes[:10])}")
            print(f"      text : {preview}…")
        if not cov:
            print("    (NONE — would be a real corpus gap, not just retrieval)")
        print(f"\n  Top-15 actually retrieved (vector):")
        _print_top15(m["top"])
    print("=" * 72)


def main() -> None:
    print("Loading evaluable eval questions...")
    questions = _load_evaluable()
    print(f"  {len(questions)} questions with rule_reference.")

    settings = Settings()
    pool = init_pool(settings.database_url, minconn=1, maxconn=3)
    corpus_version = _resolve_corpus_version(pool, settings)
    print(f"  corpus_version = {corpus_version}")

    print("Loading embedder (takes ~5-10s)...")
    embedder = Embedder.load(settings.model_name)
    print("  Embedder ready.")

    print("Loading corpus chunks for gold-chunk lookup...")
    all_chunks = _load_all_chunks(pool, corpus_version)
    print(f"  {len(all_chunks)} chunks in corpus {corpus_version}.\n")

    try:
        misses = diagnose(questions, embedder, pool, corpus_version, all_chunks, settings)
    finally:
        close_pool(pool)

    _print_report(misses)


if __name__ == "__main__":
    main()
