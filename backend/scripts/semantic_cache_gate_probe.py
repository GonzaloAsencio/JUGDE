"""Flip-gate harness for the semantic cache (plan 2.3) — e2e, ZERO LLM.

semantic_cache_probe.py picked the threshold OFFLINE (pure cosines: non-hard
ceiling 0.763, paraphrase floor 0.874, threshold 0.85 inside the measured
band). This harness gates the flip by exercising the REAL production path on
the REAL shared infrastructure — the Supabase ANN query with its namespace
filters, freshness window, and the Redis pointer round-trip — which the
offline probe never touched.

It costs zero LLM because the gate measures MATCHING, not answer quality: the
seeded answers are SENTINELS ("SEED:<id>"), and a paraphrase hit must resolve
the right sentinel back out of Redis.

ISOLATION (the reason this is safe to run against shared infra): everything is
seeded under ``prompt_version + "+gate-probe"``. The ANN query filters on
prompt_version and make_cache_key hashes it, so a prod lookup can never match
a gate row and a gate lookup can never match a prod row — same mechanism that
keeps `+hard-routing` answers out of the flag-off cache. Claim 3 spot-checks
this instead of trusting it. Cleanup DELETEs every seeded row on the way out
(even on failure) and the Redis sentinels carry a 1h TTL.

The pre-committed rule lives in docs/improvement-plan.md §2.3:
  1. PARAPHRASE HITS: each calibration paraphrase (the hand-written rewordings
     in semantic_cache_probe._PARAPHRASES) matches ITS OWN original at
     similarity >= threshold AND the pointer resolves that original's sentinel
     from Redis. Any miss or wrong-question match KILLS the flag.
  2. ZERO CROSS-MATCHES: leave-one-out over every seeded non-hard question
     (forget -> lookup -> re-remember): zero matches >= threshold to a
     DIFFERENT question. Any cross-match is printed for the hand-read the plan
     requires; a differing ruling KILLS.
  3. ISOLATION: a lookup under prod's prompt_version must not see gate rows.

Usage (from backend/):
    python -m scripts.semantic_cache_gate_probe

Requires: DATABASE_URL (migration 007 applied), UPSTASH_REDIS_URL/TOKEN, and
the local embedder. Costs zero LLM tokens.
"""
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app import semantic_cache
from app.cache import (
    directive_key,
    get_cached,
    init_redis,
    is_enabled,
    make_cache_key,
    set_cached,
)
from app.config import Settings
from app.db import close_pool, init_pool
from app.rag.embedder import Embedder
from app.rag.pipeline import (
    _detect_entities,
    _detect_keywords,
    _extract_tags,
    _semantic_cache_is_safe,
)
from scripts.retrieval_probe import _resolve_corpus_version
from scripts.semantic_cache_probe import _PARAPHRASES

_EVAL_SET = Path(__file__).parent.parent / "data" / "eval_set.json"

GATE_NAMESPACE_SUFFIX = "+gate-probe"
# Sentinels must outlive the run but not the day: the DB rows are DELETEd in
# the finally block, and any Redis sentinel a crash leaves behind expires on
# its own — under the gate namespace no prod lookup can reach it meanwhile.
SEED_TTL_S = 3600


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_semantic_cache_gate_probe.py)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParaphraseResult:
    """One calibration paraphrase's trip through the real lookup path."""
    original: str
    paraphrase: str
    matched_question: str | None   # None = no match >= threshold
    similarity: float | None
    sentinel_ok: bool              # Redis returned the ORIGINAL's sentinel

    @property
    def ok(self) -> bool:
        return self.matched_question == self.original and self.sentinel_ok


@dataclass(frozen=True)
class CrossMatch:
    """A leave-one-out lookup that matched a DIFFERENT question >= threshold."""
    question: str
    matched_question: str
    similarity: float


def gate_verdict(
    paraphrases: list[ParaphraseResult],
    cross_matches: list[CrossMatch],
    isolation_ok: bool,
) -> str:
    """Apply the pre-committed rule (plan §2.3).

    DEAD on any paraphrase failure (claim 1) or broken isolation (claim 3).
    Cross-matches (claim 2) do not auto-kill — the rule sends them to a human
    read, so the verdict is NEEDS_HUMAN_READ, never a silent ALIVE.
    An empty paraphrase list is a broken run, not a passing one.
    """
    if not paraphrases or any(not p.ok for p in paraphrases) or not isolation_ok:
        return "DEAD"
    if cross_matches:
        return "NEEDS_HUMAN_READ"
    return "ALIVE"


# ---------------------------------------------------------------------------
# DB/Redis-driven harness (manual run — not unit-tested)
# ---------------------------------------------------------------------------

def _load_questions() -> list[dict]:
    data = json.loads(_EVAL_SET.read_text(encoding="utf-8"))
    return data["questions"] if isinstance(data, dict) and "questions" in data else data


@dataclass(frozen=True)
class _Seed:
    qid: str
    question: str        # raw, tags included — what make_cache_key hashes
    base_question: str   # tag-stripped — what gets embedded
    cache_key: str
    dkey: str
    embedding: list


def _classify_non_hard(question: str, pool, corpus_version: str) -> tuple[bool, str, str]:
    """(is_non_hard, base_question, dkey) — the production classification."""
    clean, explicit_tags = _extract_tags(question)
    base = clean or question
    entities = _detect_entities(base, pool, corpus_version, "cache-gate-probe")
    safe = _semantic_cache_is_safe(
        card_count=entities.card_count([]),
        keyword_count=len(_detect_keywords(base)),
    )
    return safe, base, directive_key(None, explicit_tags)


def _seed_all(questions, embedder, pool, corpus_version, gate_pv, settings) -> list[_Seed]:
    """Seed every non-hard question (evals + paraphrase originals) with a
    sentinel answer in Redis and a pointer row in cached_questions."""
    to_seed: list[tuple[str, str]] = [
        (q.get("id", "?"), q["question"]) for q in questions
    ]
    eval_texts = {q["question"] for q in questions}
    for i, (original, _) in enumerate(_PARAPHRASES):
        if original not in eval_texts:
            to_seed.append((f"orig-{i}", original))

    seeds: list[_Seed] = []
    for qid, question in to_seed:
        non_hard, base, dkey = _classify_non_hard(question, pool, corpus_version)
        if not non_hard:
            continue
        embedding = embedder.encode(base)
        cache_key = make_cache_key(question, corpus_version, None, gate_pv)
        set_cached(
            cache_key,
            json.dumps({"answer": f"SEED:{qid}", "citations": [], "confidence": 0.99}),
            ttl=SEED_TTL_S,
        )
        semantic_cache.remember(
            pool, base, embedding, cache_key,
            corpus_version=corpus_version, prompt_version=gate_pv, directive_key=dkey,
        )
        seeds.append(_Seed(qid, question, base, cache_key, dkey, embedding))
    return seeds


def _lookup(pool, embedding, corpus_version, gate_pv, dkey, settings):
    return semantic_cache.lookup(
        pool, embedding,
        corpus_version=corpus_version,
        prompt_version=gate_pv,
        directive_key=dkey,
        threshold=settings.semantic_cache_threshold,
        ttl_s=settings.cache_ttl_s,
    )


def _run_paraphrases(seeds, embedder, pool, corpus_version, gate_pv, settings):
    by_base = {s.base_question: s for s in seeds}
    by_raw = {s.question: s for s in seeds}
    results = []
    for original, paraphrase in _PARAPHRASES:
        seed = by_raw.get(original) or by_base.get(original)
        if seed is None:
            # Original classified hard (or never seeded): the calibration set
            # and the safety gate disagree — that is itself a finding.
            results.append(ParaphraseResult(original, paraphrase, None, None, False))
            continue
        clean, tags = _extract_tags(paraphrase)
        base = clean or paraphrase
        match = _lookup(
            pool, embedder.encode(base), corpus_version, gate_pv,
            directive_key(None, tags), settings,
        )
        if match is None:
            results.append(ParaphraseResult(seed.base_question, paraphrase, None, None, False))
            continue
        key, matched_q, sim = match
        raw = get_cached(key)
        sentinel_ok = False
        if raw is not None:
            try:
                sentinel_ok = json.loads(raw)["answer"] == f"SEED:{seed.qid}"
            except Exception:
                sentinel_ok = False
        results.append(ParaphraseResult(seed.base_question, paraphrase, matched_q, sim, sentinel_ok))
    return results


def _run_leave_one_out(seeds, pool, corpus_version, gate_pv, settings) -> list[CrossMatch]:
    cross: list[CrossMatch] = []
    for s in seeds:
        semantic_cache.forget(pool, s.cache_key)
        match = _lookup(pool, s.embedding, corpus_version, gate_pv, s.dkey, settings)
        if match is not None:
            _, matched_q, sim = match
            cross.append(CrossMatch(s.base_question, matched_q, sim))
        semantic_cache.remember(
            pool, s.base_question, s.embedding, s.cache_key,
            corpus_version=corpus_version, prompt_version=gate_pv, directive_key=s.dkey,
        )
    return cross


def _check_isolation(seeds, pool, corpus_version, settings) -> bool:
    """A lookup under PROD's prompt_version must never return a gate row.

    Matching a real prod row here is fine (prod may have cached the same
    question); returning one of OUR sentinel keys is the breach.
    """
    seeded_keys = {s.cache_key for s in seeds}
    for s in seeds[:3]:
        match = semantic_cache.lookup(
            pool, s.embedding,
            corpus_version=corpus_version,
            prompt_version=settings.prompt_version,
            directive_key=s.dkey,
            threshold=settings.semantic_cache_threshold,
            ttl_s=settings.cache_ttl_s,
        )
        if match is not None and match[0] in seeded_keys:
            return False
    return True


def _print_report(paraphrases, cross, isolation_ok, verdict, threshold) -> None:
    print("\n" + "=" * 64)
    print("SEMANTIC CACHE FLIP GATE (plan 2.3) — e2e, zero LLM")
    print("=" * 64)

    print(f"\n  Claim 1 — paraphrase hits (threshold {threshold}):")
    for p in paraphrases:
        status = "HIT [OK]" if p.ok else "FAIL"
        sim = f"{p.similarity:.4f}" if p.similarity is not None else "--"
        print(f"    [{status:8s}] sim={sim}")
        print(f"      asked  : {p.paraphrase}")
        print(f"      matched: {p.matched_question or '(no match >= threshold)'}")
        if p.matched_question and not p.sentinel_ok:
            print("      *** matched but Redis returned the WRONG/no sentinel")

    print(f"\n  Claim 2 — leave-one-out cross-matches: {len(cross)}")
    for c in cross:
        print(f"    sim={c.similarity:.4f}  *** READ BY HAND — same ruling?")
        print(f"      asked  : {c.question}")
        print(f"      matched: {c.matched_question}")

    print(f"\n  Claim 3 — namespace isolation from prod: "
          f"{'[OK]' if isolation_ok else 'BROKEN — gate rows visible to prod lookups'}")

    print(f"\n  VERDICT: {verdict}")
    if verdict == "NEEDS_HUMAN_READ":
        print("  (cross-matches above go to the hand-read the plan requires)")
    print("=" * 64)


def main() -> None:
    settings = Settings()
    if not (settings.upstash_redis_url and settings.upstash_redis_token):
        sys.exit("Upstash credentials missing — the gate needs live Redis.")
    init_redis(settings.upstash_redis_url, settings.upstash_redis_token)
    if not is_enabled():
        sys.exit("Redis init failed — the gate needs live Redis.")

    questions = _load_questions()
    print(f"Loaded {len(questions)} eval questions + {len(_PARAPHRASES)} calibration paraphrases.")

    pool = init_pool(settings.database_url, minconn=1, maxconn=3)
    corpus_version = _resolve_corpus_version(pool, settings)
    gate_pv = settings.prompt_version + GATE_NAMESPACE_SUFFIX
    print(f"  corpus_version = {corpus_version}")
    print(f"  gate namespace = {gate_pv!r} (prod runs {settings.prompt_version!r})")

    print("Loading embedder (takes ~5-10s)...")
    embedder = Embedder.load(settings.model_name)
    print("  Embedder ready.\n")

    seeds: list[_Seed] = []
    try:
        print("Seeding non-hard questions with sentinels...")
        seeds = _seed_all(questions, embedder, pool, corpus_version, gate_pv, settings)
        print(f"  {len(seeds)} seeded (hard questions excluded by the safety gate).\n")

        paraphrases = _run_paraphrases(
            seeds, embedder, pool, corpus_version, gate_pv, settings)
        cross = _run_leave_one_out(seeds, pool, corpus_version, gate_pv, settings)
        isolation_ok = _check_isolation(seeds, pool, corpus_version, settings)
        verdict = gate_verdict(paraphrases, cross, isolation_ok)
    finally:
        for s in seeds:
            semantic_cache.forget(pool, s.cache_key)
        close_pool(pool)
        print(f"\nCleanup: {len(seeds)} seeded rows deleted "
              f"(Redis sentinels expire in {SEED_TTL_S}s under the gate namespace).")

    _print_report(paraphrases, cross, isolation_ok, verdict, settings.semantic_cache_threshold)


if __name__ == "__main__":
    main()
