"""Offline experiment: does query transformation lift retrieval recall?

Compares three ways of turning a question into the text we embed, measured with
the deterministic retrieval probe (no judge):

  raw     - embed the question as-is (current production behaviour on Gemini)
  rewrite - rephrase with official terminology (the existing _REWRITE_PROMPT)
  hyde    - generate a short hypothetical ANSWER and embed THAT (HyDE)

The oracle ceiling test (hand-written ideal HyDE passages) showed eval-007
15->4, eval-008 14->6, eval-002 None->15. This measures how close an automatic
LLM rewrite gets to that ceiling, and crucially whether it REGRESSES questions
that already retrieve well.

Usage (from backend/):
    python -m scripts.rewrite_experiment

Requires: DATABASE_URL + corpus, and an openai_compat LLM (LLM_BASE_URL/
LLM_API_KEY/LLM_MODEL). Does NOT use the judge.
"""
import openai
from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, get_conn, init_pool
from app.rag.embedder import Embedder
from app.rag.retrieval import Chunk, _authority_boost, hybrid_search
from scripts.eval_judge import _parse_refs
from scripts.retrieval_probe import (
    TOP_K,
    TOP_K_FETCH,
    _load_evaluable,
    first_covering_rank,
    recall_at_k,
)

_HYDE_PROMPT = """\
You answer rules questions about the Riftbound trading card game.
Write a short, confident hypothetical answer (2-3 sentences) to the question
below, using official rulebook terminology. It does not need to be perfectly
correct — it will be used to retrieve the real rule by semantic similarity.
Output only the answer.

Question: {question}
Answer:"""


def _hyde(question: str, *, base_url: str, api_key: str, model: str) -> str:
    """Generate a hypothetical answer (HyDE). Falls back to the question on error."""
    try:
        client = openai.OpenAI(base_url=base_url, api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _HYDE_PROMPT.format(question=question)}],
            temperature=0.0,
            max_tokens=160,
            timeout=15.0,
        )
        out = resp.choices[0].message.content
        if out:
            return out.strip()
    except Exception as e:
        print(f"    [hyde error] {str(e)[:80]}")
    return question


def _fuse(arm_a: list[Chunk], arm_b: list[Chunk], weight_b: float, rrf_k: int = 60,
          top_k: int = TOP_K) -> list[Chunk]:
    """RRF-fuse two retrieval result lists. Arm A is primary (tie-break winner);
    arm B is scaled by *weight_b* so it can ADD signal but, when down-weighted,
    never displace a strong arm-A hit. Authority boost applies to both arms so
    errata/patch keep priority (mirrors production _rrf_fuse)."""
    scores: dict[str, float] = {}
    by_id: dict[str, Chunk] = {}
    in_a: set[str] = set()
    for rank0, ch in enumerate(arm_a):
        scores[ch.id] = scores.get(ch.id, 0.0) + _authority_boost(ch.source_type) / (rrf_k + rank0 + 1)
        by_id[ch.id] = ch
        in_a.add(ch.id)
    for rank0, ch in enumerate(arm_b):
        scores[ch.id] = scores.get(ch.id, 0.0) + weight_b * _authority_boost(ch.source_type) / (rrf_k + rank0 + 1)
        by_id.setdefault(ch.id, ch)
    order = sorted(scores, key=lambda cid: (-scores[cid], 0 if cid in in_a else 1))
    return [by_id[cid] for cid in order[:top_k]]


def _retrieve(text, embedder, pool, cv) -> list[Chunk]:
    emb = embedder.encode(text)
    return hybrid_search(pool, emb, text, cv, top_k=TOP_K, top_k_fetch=TOP_K_FETCH)


def main() -> None:
    s = Settings()
    base_url, api_key, model = s.llm_base_url, s.llm_api_key, s.llm_model
    if not (base_url and api_key and model):
        raise SystemExit("Set LLM_BASE_URL / LLM_API_KEY / LLM_MODEL for the rewrite experiment.")

    questions = _load_evaluable()
    pool = init_pool(s.database_url, 1, 3)
    with get_conn(pool) as c:
        with c.cursor() as cur:
            cur.execute("SELECT MAX(corpus_version) FROM corpus_chunks")
            cv = cur.fetchone()[0]
    embedder = Embedder.load(s.model_name)
    print(f"corpus={cv}  model={model}  {len(questions)} evaluable questions\n")

    # One LLM pass: generate the HyDE passage once per question, retrieve raw and
    # hyde once, then derive every strategy (incl. fusions) from those two lists.
    strategies = ["raw", "hyde", "fuse_eq", "fuse_dw"]
    ranks = {name: [] for name in strategies}
    ids = []
    try:
        for q in questions:
            refs = _parse_refs(q["rule_reference"])
            raw_chunks = _retrieve(q["question"], embedder, pool, cv)
            hyde_text = _hyde(q["question"], base_url=base_url, api_key=api_key, model=model)
            hyde_chunks = _retrieve(hyde_text, embedder, pool, cv)

            per = {
                "raw": raw_chunks,
                "hyde": hyde_chunks,
                "fuse_eq": _fuse(raw_chunks, hyde_chunks, weight_b=1.0),
                "fuse_dw": _fuse(raw_chunks, hyde_chunks, weight_b=0.3),
            }
            for name in strategies:
                ranks[name].append(first_covering_rank(refs, per[name]))
            ids.append(q["id"])
            print(f"  {q['id']} done")
    finally:
        close_pool(pool)

    print(f"\n{'strategy':8s}  @5    @10   @15   (raw is the production baseline)")
    for name in strategies:
        print(f"{name:8s}  {recall_at_k(ranks[name], 5):>4.0%}  "
              f"{recall_at_k(ranks[name], 10):>4.0%}  {recall_at_k(ranks[name], 15):>4.0%}")

    print(f"\n{'id':10s} {'raw':>4s} {'hyde':>5s} {'fuse_eq':>8s} {'fuse_dw':>8s}")
    for i, qid in enumerate(ids):
        cell = lambda n: str(ranks[n][i])
        print(f"{qid:10s} {cell('raw'):>4s} {cell('hyde'):>5s} {cell('fuse_eq'):>8s} {cell('fuse_dw'):>8s}")


if __name__ == "__main__":
    main()
