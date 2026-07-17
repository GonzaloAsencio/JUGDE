"""Context-coverage probe — measures whether each gold rule reaches the context
production would ACTUALLY build for a question, WITHOUT an LLM (embedder + DB).

Why this exists: re-running the full eval costs Gemini credits and the judge is
noisy. This probe isolates retrieval, so we know which lever to pull before
spending on a full eval run.

What it measures (the headline): for every evaluable question it resolves the
REAL production path and reports whether EVERY gold ref is present in the
resulting generation context —

  * routed (is_hard_query + the flag) -> context = the stuffed full rulebook
  * otherwise                         -> context = _retrieve's assembly
    (tagged cards + hybrid_search + _assemble_context + family completion)

The raw hybrid/vector/fts recall@k figures are kept BELOW that headline as
diagnostics only: they say WHY a rule is missing (never retrieved vs ranked
low). They deliberately UNDER-report coverage, because production layers card
injection and family completion on top of the arm. Do not quote them as the
production signal.

Three blind spots this probe had, and what they cost (2026-07-16):
  1. It ignored routing entirely, so it INVENTED gaps — that produced the
     phantom "383-family systemic gap" (5 questions) when 4 of the 5 route and
     answer correctly citing 383.3.d.
  2. chunk_covers_refs scores a hit on ANY gold ref, which HID real gaps —
     eval-020 has 816 at rank 1 and 383.3.d nowhere, and looked healthy. Both
     the any-ref and strict (all-refs) figures are now reported; the spread is
     the size of the lie.
  3. It measured the raw hybrid_search arm and called it "the context", which
     UNDER-reported — eval-030's family siblings arrive via family completion,
     invisible to the arm.

Known limitation, stated so nobody re-learns it the hard way: HyDE is off here
(it would cost an LLM call), but production DOES fuse a HyDE arm for non-routed
questions. Non-routed coverage is therefore a FLOOR, not an exact prediction.

Usage (from backend/):
    python -m scripts.retrieval_probe

Requires: DATABASE_URL + corpus ingestado. Never SPENDS Gemini quota — but the
key must still be PRESENT: Settings() fails closed without it (llm_provider
defaults to gemini, and hard_query_routing=True demands gemini_api_key), so the
probe dies at construction, not at a call site. Zero quota, not zero config.
"""
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, get_conn, init_pool
from app.rag.embedder import Embedder
from app.rag.pipeline import (
    _KNOWN_KEYWORDS,
    _detect_entities,
    _detect_keywords,
    _extract_tags,
    _retrieve,
)
from app.rag.provider import LLMProvider
from app.rag.retrieval import fts_search, hybrid_search, vector_search
from app.rag.routing import build_stuffed_chunks, is_hard_query
from app.rag.rules import extract_rule_codes
from scripts.eval_judge import _parse_refs, _rule_codes_cover


class _NoHydeProvider(LLMProvider):
    """Zero-quota stand-in for the LLM provider.

    _retrieve only touches the provider for its HyDE arm. The probe's whole
    point is costing nothing, so HyDE stays off and this returns an empty
    passage — the same HyDE-off convention every deterministic probe in this
    repo uses. Consequence to keep in mind when reading the numbers: for
    NON-routed questions production also fuses a HyDE arm, so the assembled
    context measured here is production's minus HyDE (a floor, not a lie).

    Subclasses the real ABC on purpose rather than duck-typing hyde(): the
    probes can't be unit-tested end-to-end (they need a DB), so a new
    abstractmethod on LLMProvider would otherwise surface as an AttributeError
    during a manual run, with CI green. Inheriting moves that to construction
    time, where tests/test_retrieval_probe.py catches it.
    """

    def generate(self, question: str, chunks, *, extra_system: str = "") -> str:
        raise NotImplementedError(
            "This probe is deterministic and must never spend LLM quota — "
            "generate() was reached, which means the retrieval path now calls "
            "the provider for something beyond HyDE. Fix the probe to model "
            "that, don't wire a real provider in here."
        )

    def hyde(self, question: str) -> str:
        return ""

_EVAL_SET = Path(__file__).parent.parent / "data" / "eval_set.json"

# Pull a deep slice so we can measure recall@5 and recall@15 in one shot, with
# enough fetch headroom for the RRF fusion to settle before truncation.
TOP_K = 15
TOP_K_FETCH = 30


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_retrieval_probe.py — no DB, no network)
# ---------------------------------------------------------------------------

def chunk_covers_refs(refs: list[str], rule_codes, source_type: str) -> bool:
    """True if a chunk covers ANY of the gold refs.

    Errata refs (``errata/...``) are covered only by an errata-source chunk —
    they have no numeric lineage. Numeric refs are covered via rule-code lineage
    (a chunk listing ``103.2`` covers ``103``; the parent does NOT cover the
    child — that would paper-hit via the family header code).
    """
    for ref in refs:
        if ref.startswith("errata/"):
            if source_type == "errata":
                return True
        elif _rule_codes_cover(ref, rule_codes):
            return True
    return False


def first_covering_rank(refs: list[str], chunks) -> int | None:
    """1-based rank of the first chunk covering the gold ref, or None if absent.

    *chunks* is the ordered retrieval result; each needs ``.content`` and
    ``.source_type``. Rule codes are extracted from the FULL content, mirroring
    how the production pipeline derives a chunk's covered rules.
    """
    for rank, chunk in enumerate(chunks, 1):
        codes = extract_rule_codes(chunk.content)
        if chunk_covers_refs(refs, codes, chunk.source_type):
            return rank
    return None


def recall_at_k(ranks: list[int | None], k: int) -> float:
    """Fraction of questions whose gold rule landed within rank *k*.

    None (never retrieved) and ranks beyond k both count as misses.

    Note this is the ANY-ref figure: a multi-ref question counts as a hit as
    soon as one of its refs is covered. See strict_recall_at_k for the
    all-refs counterpart, and per_ref_ranks for where they diverge.
    """
    if not ranks:
        return 0.0
    hits = sum(1 for r in ranks if r is not None and r <= k)
    return hits / len(ranks)


def per_ref_ranks(refs: list[str], chunks) -> dict[str, int | None]:
    """Rank of the first chunk covering EACH gold ref, independently.

    first_covering_rank collapses a multi-ref question to its luckiest ref.
    This keeps them apart, which is the only way a partially-covered question
    is visible: eval-020 (gold "816, 383.3.d") retrieves 816 at rank 1 and
    never retrieves 383.3.d, yet scored a clean h=1 before this existed.

    One pass, extracting each chunk's rule codes ONCE and testing every ref
    against them: a routed context carries the whole rulebook in a single
    chunk, so a per-ref pass would re-regex ~500KB once per ref.
    """
    ranks: dict[str, int | None] = {ref: None for ref in refs}
    for rank, chunk in enumerate(chunks, 1):
        if all(v is not None for v in ranks.values()):
            break
        codes = extract_rule_codes(chunk.content)
        for ref in refs:
            if ranks[ref] is None and chunk_covers_refs([ref], codes, chunk.source_type):
                ranks[ref] = rank
    return ranks


def fully_covered(per_ref: dict[str, int | None]) -> bool:
    """True if EVERY gold ref reached the context (rank irrelevant, presence isn't).

    This is the headline question for a generation context: the model sees the
    whole context, so what matters is whether each rule it needs is in there.
    An empty ref map is not evidence of coverage.
    """
    return bool(per_ref) and all(v is not None for v in per_ref.values())


def strict_recall_at_k(per_ref: list[dict[str, int | None]], k: int) -> float:
    """Fraction of questions with EVERY gold ref covered within rank *k*.

    The conservative counterpart to recall_at_k. Reported alongside it rather
    than replacing it: where a question's refs are alternatives, any-ref is the
    right rule; where they're conjuncts (you need both rules to answer), only
    this figure is honest. The spread between the two is the measurement's
    blind spot, quantified.
    """
    if not per_ref:
        return 0.0
    hits = sum(
        1 for ranks in per_ref
        if ranks and all(r is not None and r <= k for r in ranks.values())
    )
    return hits / len(per_ref)


def source_distribution(source_types: list[str]) -> dict:
    """Count of each source_type in a result slice (e.g. the top-5)."""
    return dict(Counter(source_types))


def routing_decision(*, card_count: int, keyword_count: int, routing_enabled: bool) -> bool:
    """True if production would swap the retrieved context for the stuffed one.

    Mirrors the production gate (pipeline.py:690): the flag AND the same
    is_hard_query classifier, so the probe's verdict can't drift from the real
    decision. When routing is off, production retrieves for everything and so
    must this probe.
    """
    return routing_enabled and is_hard_query(
        card_count=card_count, keyword_count=keyword_count
    )


@dataclass(frozen=True)
class ProductionContext:
    """What production would ACTUALLY feed the generator, and how it got there.

    *stuffing_unavailable* is the loud bit: it means the question SHOULD have
    routed but build_stuffed_chunks returned None (never-raise: a missing or
    corrupt rulebook.md logs a structlog warning the probe's stdout never
    shows). Every report must shout about it, because the alternative is a
    probe printing a healthy figure for a bucket it never measured.
    """
    chunks: list
    routed: bool
    entities: object
    card_count: int
    keyword_count: int
    embedding: list
    base_question: str
    stuffing_unavailable: bool


def resolve_production_context(
    question, embedder, pool, provider, settings, corpus_version, query_id,
    *, routing_enabled: bool,
) -> ProductionContext:
    """THE single copy of "what context would production build for this question?".

    This resolution used to live in three probes as three hand-copies, and the
    third drifted: miss_diagnosis kept routed=True through the degrade path, so
    a ref absent from a 5-chunk RAG context was reported as absent from the FULL
    rulebook — the strongest possible claim from the weakest measurement.
    Re-syncing copies is what this branch did elsewhere; it does not stop the
    fourth copy. One function means the probes cannot disagree by construction.

    Mirrors production exactly (pipeline.py:641-709):
      * entities + keywords are read off the TAG-STRIPPED question, because that
        is what production feeds the gate;
      * routed -> context = build_stuffed_chunks (the full rulebook);
      * stuffing unavailable -> production sets routed=True ONLY when stuffed is
        not None, so we degrade to the RAG path AND clear the label;
      * otherwise -> context = _retrieve's real assembly, HyDE off.
    """
    clean_question, _ = _extract_tags(question)
    base_question = clean_question or question
    embedding = embedder.encode(base_question)

    entities = _detect_entities(base_question, pool, corpus_version, query_id)
    card_count = entities.card_count([])
    keyword_count = len(_detect_keywords(base_question))
    routed = routing_decision(
        card_count=card_count,
        keyword_count=keyword_count,
        routing_enabled=routing_enabled,
    )

    chunks = None
    stuffing_unavailable = False
    if routed:
        chunks = build_stuffed_chunks(base_question, known_keywords=_KNOWN_KEYWORDS)
        if chunks is None:
            routed = False
            stuffing_unavailable = True

    if chunks is None:
        # _retrieve takes the RAW question — it strips tags itself.
        chunks, _, _, _, _ = _retrieve(
            question, embedder, pool, provider, settings, None, corpus_version,
            query_id, question_embedding=embedding, entities=entities, skip_hyde=True,
        )

    return ProductionContext(
        chunks=chunks,
        routed=routed,
        entities=entities,
        card_count=card_count,
        keyword_count=keyword_count,
        embedding=embedding,
        base_question=base_question,
        stuffing_unavailable=stuffing_unavailable,
    )


def split_by_route(results: list[dict]) -> tuple[list[dict], list[dict]]:
    """Partition probe results into (routed, retrieved).

    Recall@k is only a production signal for the *retrieved* bucket. A routed
    question whose gold rule never surfaces in hybrid_search is not a miss —
    the stuffed rulebook carries it — and folding it into the recall figure is
    exactly what manufactured the phantom 383 gap.
    """
    routed = [r for r in results if r["routed"]]
    retrieved = [r for r in results if not r["routed"]]
    return routed, retrieved


# ---------------------------------------------------------------------------
# DB-driven probe (manual run — not unit-tested)
# ---------------------------------------------------------------------------

def _load_evaluable() -> list[dict]:
    """Eval questions that carry a rule_reference (the recall-evaluable ones)."""
    data = json.loads(_EVAL_SET.read_text(encoding="utf-8"))
    questions = data["questions"] if isinstance(data, dict) and "questions" in data else data
    return [q for q in questions if q.get("rule_reference") is not None]


def _resolve_corpus_version(pool, settings: Settings) -> str:
    if settings.corpus_version and settings.corpus_version != "latest":
        return settings.corpus_version
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(corpus_version) FROM corpus_chunks")
            row = cur.fetchone()
    if row is None or row[0] is None:
        print("WARNING: corpus_chunks is empty — retrieval will return nothing.", file=sys.stderr)
        return "unknown"
    return row[0]


def _strategy_rank(refs, chunks) -> int | None:
    return first_covering_rank(refs, chunks)


def run_probe(
    questions, embedder, pool, corpus_version, settings, *, routing_enabled: bool
) -> list[dict]:
    """Measure gold-rule presence in the context production would ACTUALLY build.

    Per question this resolves the real path: entity detection and the keyword
    scan feed the same is_hard_query gate production uses, then

      * routed    -> context = build_stuffed_chunks (the full rulebook)
      * not routed -> context = _retrieve (the real assembly: tagged_lookup
                      cards + hybrid_search + _assemble_context +
                      _complete_keyword_families), HyDE off

    Calling _retrieve rather than re-implementing it is deliberate: a probe that
    approximates the pipeline drifts from it, and drift is exactly what made
    this tool lie. The raw hybrid/vector/fts ranks are still recorded as
    diagnostics — they say WHY a rule is missing (never retrieved vs ranked
    low) — but presence in the assembled context is the production signal.
    """
    results = []
    provider = _NoHydeProvider()
    for q in questions:
        refs = _parse_refs(q["rule_reference"])
        question = q["question"]

        resolved = resolve_production_context(
            question, embedder, pool, provider, settings, corpus_version, "probe",
            routing_enabled=routing_enabled,
        )
        context = resolved.chunks
        routed = resolved.routed
        base_question = resolved.base_question
        embedding = resolved.embedding
        card_count = resolved.card_count
        keyword_count = resolved.keyword_count

        # Yes, _retrieve above already ran a hybrid_search, and this runs another.
        # They are NOT the same query and deduplicating them would cost the
        # signal this one exists for: production fetches at top_k_fetch=15 and
        # ships top_k=5, while the diagnostic deliberately goes deeper
        # (15/30) to separate "gold sits at rank 12" (ranking problem) from
        # "gold is nowhere" (chunking problem). Collapsing them would either
        # shallow the diagnostic or force _retrieve to expose its internals for
        # a probe's benefit. One extra query in a manual tool is the cheaper
        # trade. (Raised in the 6.3 review; kept on purpose.)
        hybrid = hybrid_search(
            pool, embedding, base_question, corpus_version,
            top_k=TOP_K, top_k_fetch=TOP_K_FETCH,
        )
        vector = vector_search(pool, embedding, corpus_version, top_k=TOP_K)
        fts = fts_search(pool, base_question, corpus_version, top_k=TOP_K)

        rank = _strategy_rank(refs, hybrid)
        top5_sources = source_distribution([c.source_type for c in hybrid[:5]])
        covering = hybrid[rank - 1] if rank is not None else None

        results.append({
            "id": q.get("id", "?"),
            "rule_reference": q["rule_reference"],
            "routed": routed,
            "stuffing_unavailable": resolved.stuffing_unavailable,
            "card_count": card_count,
            "keyword_count": keyword_count,
            "context_per_ref": per_ref_ranks(refs, context),
            "context_size": len(context),
            "hybrid_per_ref": per_ref_ranks(refs, hybrid),
            "hybrid_rank": rank,
            "vector_rank": _strategy_rank(refs, vector),
            "fts_rank": _strategy_rank(refs, fts),
            "covering_source": covering.source_type if covering else None,
            "top5_sources": top5_sources,
        })
    return results


def _print_report(results: list[dict], *, routing_enabled: bool) -> None:
    routed, retrieved = split_by_route(results)
    total = len(results)

    print("\n" + "=" * 64)
    print("RETRIEVAL PROBE (deterministic — no LLM, HyDE off)")
    print("=" * 64)
    print(f"  Evaluable questions : {total}")
    print(f"  hard_query_routing  : {'ON' if routing_enabled else 'OFF'}")
    print(f"  routed (stuffed ctx): {len(routed)}   retrieved (RAG ctx): {len(retrieved)}")

    # Never let a degraded run pass for a healthy one: build_stuffed_chunks is
    # never-raise, so a missing/corrupt rulebook.md silently sends every routed
    # question down the RAG path. Without this the report would print a fine
    # number for a bucket it never measured.
    degraded = [r["id"] for r in results if r["stuffing_unavailable"]]
    if degraded:
        print(f"\n  *** WARNING: stuffing UNAVAILABLE for {len(degraded)} question(s) "
              f"that should have routed.")
        print("      build_stuffed_chunks returned None (missing/corrupt "
              "data/processed/rulebook.md?).")
        print("      They were measured on the RAG path instead. The routed "
              "bucket below is NOT a full measurement.")
        print(f"      Affected: {', '.join(degraded)}")

    # THE headline: is every gold rule in the context production would build?
    # Everything below this is diagnosis of the misses.
    print("\n  --- GENERATION CONTEXT COVERAGE (the production signal) ---")
    full = [r for r in results if fully_covered(r["context_per_ref"])]
    print(f"  every gold ref present in context : {len(full)}/{total} "
          f"({len(full) / total:.0%})" if total else "  (no questions)")
    gaps = [r for r in results if not fully_covered(r["context_per_ref"])]
    if gaps:
        print("\n  REAL GAPS (a gold rule never reaches the model):")
        for r in gaps:
            missing = [k for k, v in r["context_per_ref"].items() if v is None]
            bucket = "routed " if r["routed"] else "rag    "
            print(f"    {r['id']:10s} [{bucket}] missing: {', '.join(missing)}")

    # Recall over the RETRIEVED bucket only. The routed questions are answered
    # from the full rulebook, so their hybrid rank predicts nothing about
    # production — averaging them in is what invented the 383 "gap".
    print("\n  --- RETRIEVED bucket: raw hybrid_search arm (diagnostic only) ---")
    print("  NOTE: this is the ARM, not the context. Production adds tagged cards")
    print("        + family completion on top, so these UNDER-report coverage.")
    if retrieved:
        hybrid_ranks = [r["hybrid_rank"] for r in retrieved]
        vector_ranks = [r["vector_rank"] for r in retrieved]
        fts_ranks = [r["fts_rank"] for r in retrieved]
        print(f"  {'strategy':8s}  @5    @10   @15   (production ships top_k=5)")
        for name, ranks in (("hybrid", hybrid_ranks), ("vector", vector_ranks), ("fts", fts_ranks)):
            print(f"  {name:8s}  {recall_at_k(ranks, 5):>4.0%}  "
                  f"{recall_at_k(ranks, 10):>4.0%}  {recall_at_k(ranks, 15):>4.0%}")

        # Any-ref (above) vs all-refs (below): the spread is how much the
        # any-ref rule flatters a multi-ref question. eval-020 is the worked
        # example — 816 at rank 1, 383.3.d nowhere, scored a clean hit.
        per_ref = [r["hybrid_per_ref"] for r in retrieved]
        print(f"  {'hybrid!':8s}  {strict_recall_at_k(per_ref, 5):>4.0%}  "
              f"{strict_recall_at_k(per_ref, 10):>4.0%}  "
              f"{strict_recall_at_k(per_ref, 15):>4.0%}   <- STRICT: every gold ref, not any")

        partial = [
            (r["id"], [k for k, v in r["hybrid_per_ref"].items() if v is None])
            for r in retrieved
            if any(v is None for v in r["hybrid_per_ref"].values())
            and any(v is not None for v in r["hybrid_per_ref"].values())
        ]
        if partial:
            ids = ", ".join(qid for qid, _ in partial)
            print(f"\n  PARTIALLY covered (any-ref scores these as hits): {ids}")
            for qid, missing_refs in partial:
                print(f"    {qid:10s} missing: {', '.join(missing_refs)}")

        # The decisive split: retrieved-but-ranked-low (ranking problem) vs
        # never-retrieved-in-15 (chunking/embedding problem).
        below_5 = sum(1 for r in hybrid_ranks if r is not None and r > 5)
        missing = sum(1 for r in hybrid_ranks if r is None)
        print()
        print(f"  RANKING problem  (retrieved but rank >5) : {below_5}/{len(retrieved)}")
        print(f"  CHUNKING problem (not in top-15 at all)  : {missing}/{len(retrieved)}")
    else:
        print("  (none — every evaluable question routes)")

    # For routed questions the only honest question is whether the gold rule
    # survives into the stuffed context they are actually answered from.
    print("\n  --- ROUTED bucket (context = full rulebook; rank is NOT a signal) ---")
    if routed:
        covered = sum(1 for r in routed if fully_covered(r["context_per_ref"]))
        print(f"  every gold ref in stuffed context : {covered}/{len(routed)}")
    else:
        print("  (none)")

    agg = Counter()
    for r in results:
        for src, n in r["top5_sources"].items():
            agg[src] += n
    print("\n  Top-5 source distribution (all questions):")
    for src, n in agg.most_common():
        print(f"    {src:12s}: {n}")

    print("\n  Per-question (route | context coverage | raw arm ranks):")
    for r in results:
        rk = r["hybrid_rank"] if r["hybrid_rank"] is not None else "--"
        vk = r["vector_rank"] if r["vector_rank"] is not None else "--"
        fk = r["fts_rank"] if r["fts_rank"] is not None else "--"
        route = "STUFFED" if r["routed"] else "rag    "
        mark = "OK  " if fully_covered(r["context_per_ref"]) else "GAP!"
        print(f"    {r['id']:10s} {route} {mark} ref={r['rule_reference']:<24s} "
              f"ctx={r['context_size']:>3} h={rk!s:>3} v={vk!s:>3} f={fk!s:>3}  "
              f"{r['covering_source'] or '-'}")
    print("\n  Legend: OK   = every gold ref reached the generation context")
    print("          GAP! = a gold rule never reaches the model (the real misses)")
    print("          ctx  = chunks in the context production would build")
    print("          h/v/f = raw arm ranks (diagnostic: why a rule is missing)")
    print("=" * 64)


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
    print("  Embedder ready.\n")

    # Read the real flag: the probe must classify questions the way the running
    # deployment does, not the way we remember it being configured.
    routing_enabled = settings.hard_query_routing
    print(f"  hard_query_routing = {routing_enabled}\n")

    try:
        results = run_probe(
            questions, embedder, pool, corpus_version, settings,
            routing_enabled=routing_enabled,
        )
    finally:
        close_pool(pool)

    _print_report(results, routing_enabled=routing_enabled)


if __name__ == "__main__":
    main()
