# Future Work

Items in this file are deferred from v1. They are not aspirational — each entry is grounded in the existing codebase, the evaluation spec, or a concrete limitation observed during development. Items are grouped by approximate effort horizon.

---

## Short-term (1–2 weeks)

### Wire the vector-only baseline and complete the ablation

A baseline run already exists against the production hybrid config using the LLM-as-judge harness (`backend/scripts/eval.py`) — see the README Results table. What's still missing:

1. Wire a vector-only path (Config A) into the harness so it can be compared against the hybrid config — today the harness only runs the production pipeline
2. Expand the eval set beyond the current 20 questions (`backend/data/eval_set.json`)
3. Improve baseline answer quality — the recorded baseline (25% correct) is low and worth diagnosing per `difficulty`/`source`
4. Use the per-source/per-difficulty breakdown to validate or refute the entity resolution threshold (ADR-004)

### Streaming responses (SSE)

The current API returns a complete JSON response after the full generate call completes. This creates a perceptible pause for users. The fix is to stream the LLM response via Server-Sent Events from FastAPI and consume the stream in the Next.js frontend. The backend skeleton exists; the blocking piece is integrating SSE with the Upstash cache (cached responses should still stream, not return instantly, to avoid a jarring UX difference).

### Extend the failure-analysis breakdown

`backend/scripts/eval_judge.py` already aggregates verdicts by `difficulty` and `source` (`aggregate_by_difficulty`, `aggregate_by_source`). Extend this to break failures down by `tags` (the per-question labels) so card-specific vs keyword vs golden-rule failures can be isolated. This sharpens the entity resolution trigger check from ADR-004.

---

## Medium-term (1 month)

### Entity resolution — Mode A (@mentions)

If the per-category failure analysis shows card-specific query failures exceed 20% of that category (the threshold from `Specs/07_entity_resolution_spec.md`), implement Mode A:

1. Frontend `@mention` autocomplete for card names
2. Backend: on `card_mentions` non-null, fetch card text from a cards lookup table and inject into the prompt context
3. Run Config D eval and fill in the results table row

The pipeline already threads `card_mentions` through `answer_question()` and the cache key — the forward hook is in place.

### Multi-language support (Spanish)

Add `es` as a supported query language. The embedding model (`bge-m3`) already supports Spanish — no re-ingestion needed. Required changes:

1. Detect query language at the API layer
2. Translate or source a Spanish rulebook corpus segment
3. Add Spanish eval set questions
4. Validate that FTS (`plainto_tsquery('simple', ...)`) handles Spanish tokenization adequately

### Feedback loop (thumbs up / down → fine-tuning signal)

The frontend spec (`Specs/08`) included thumbs up/down buttons that were descoped from v1. Implementing them would:

1. Add a `POST /feedback` endpoint that records `query_id`, `answer_id`, `label` (positive/negative), and `user_comment` to Postgres
2. Surface feedback counts in the Langfuse dashboard via custom events
3. Use accumulated feedback labels as a signal for future prompt tuning or eval set expansion

### Cross-encoder reranker — Config C

`enable_reranker: bool = False` is already in `backend/app/config.py`. Config C in the results table is "not implemented" because the cross-encoder is not wired. Implementing it requires:

1. Select a cross-encoder model (e.g., `cross-encoder/ms-marco-MiniLM-L-6-v2`)
2. Wire it in `retrieval.py` after RRF fusion: take the top-5 RRF results, rerank with the cross-encoder, return reranked top-k
3. Run the harness with the reranker enabled and compare to the hybrid baseline

### Faithfulness measurement (RAGAS — optional)

The current harness measures answer correctness (LLM-as-judge) and retrieval recall, but it does **not** measure *faithfulness* — whether the answer is actually grounded in the retrieved corpus versus the model's own training knowledge. That is the metric most aligned with this project's core promise ("the judge never invents rules").

Today that risk is mitigated by **behaviour**, not measurement: the system prompt forces grounding and citations, `post_gen_validate` strips hallucinated citations, and `query.no_info_despite_context` is logged. Adding [RAGAS](https://github.com/explodinggradients/ragas) would put a *number* on faithfulness (plus answer relevancy and context precision).

This is a **nice-to-have, not a blocker** — see ADR-006 for why LLM-as-judge was chosen over RAGAS for v1. Only worth the extra dependency if grounding quality becomes a measured concern.

---

## Deferred hardening (deliberately descoped)

These came out of the risk audit. The high-value fixes were shipped (concurrency
model, pool resilience, empty-LLM-response handling, fail-closed auth, shared
rate-limit storage, log sanitisation, trigram index, pattern caching, whole-word
confidence). The items below were **consciously deferred** — the risk/reward
didn't justify doing them now.

### True async I/O stack

The concurrency fix made the request path sync + threadpool, which matches the
reality that every driver (psycopg2, upstash-redis HTTP, sentence-transformers,
the Gemini/OpenAI clients) is blocking. If sustained traffic ever outgrows the
threadpool, migrate to a genuinely async stack: `psycopg` (v3) async pool,
`redis.asyncio`, and async LLM clients over httpx. This is a rewrite of the DB,
cache, and generation layers — only worth it when measured throughput demands it.

### Collapse `tagged_lookup`'s N+1 into one round-trip

`tagged_lookup` still issues one query per tag. The trigram index (migration 006)
made each query indexable, so the remaining cost is N round-trips with a small N.
A `unnest(tags) WITH ORDINALITY` + `CROSS JOIN LATERAL` query would collapse it to
one round-trip while preserving the per-tag `LIMIT 2` semantics. Deferred because
it rewrites tuned retrieval SQL that needs validation against a real Postgres +
the recall probes, not just unit tests.

### Provider call-logic ownership

`app/rag/provider.py` imports call helpers (`_call_gemini`,
`_call_openai_compat_raw`, `_hyde_openai_compat`) from `app/rag/generation.py`.
This reads like a leaky abstraction, but `_call_gemini` is also reused by
`scripts/eval_judge.py`, so `generation.py` is legitimately a shared
generation-utilities module, not provider internals that leaked. A full
relocation into the provider classes would break that reuse for no behavioural
gain, so it was left as-is.

### Remove dormant FTS / query-rewrite code

`fts_search` / `_FTS_SQL` (the FTS arm is dormant — vector-only won the probe) and
`_rewrite_openai_compat` / `rewrite_query` (the rewrite path was dropped) are
unused in the live path but heavily documented as intentionally-dormant for future
re-evaluation. Physically moving them to an `experiments/` module risks breaking
imports for no functional gain; left in place with their explanatory comments.

---

## Long-term (3+ months)

### Cost optimization at scale

At sustained production traffic, the Gemini free tier will be exhausted. Cost optimization strategies to explore:

- **Semantic cache hit rate improvement**: the current cache uses an exact SHA-256 key over the normalized question. A semantic cache (ANN lookup over question embeddings) could catch paraphrase duplicates and increase hit rate significantly, reducing LLM calls.
- **Prompt compression**: reduce token count in the prompt by summarizing or truncating retrieved chunks more aggressively while preserving answer quality.
- **Tiered model routing**: route simple factual queries to a lighter/cheaper model and complex multi-step queries to a larger model.

### Cards database ingestion

Build a separate ingestion pipeline that loads card data (name, type, text, keywords) from a structured source (Riftcodex or official API if available) into a `cards` table. This enables:

- Entity resolution Mode A and B (see medium-term)
- Card-text citation in answers ("According to the Veilbreaker card text: ...")
- Card-specific eval questions with ground truth from the cards DB

### Multi-rulebook support

The corpus is currently a single `rulebook.md` + `errata.md`. Add support for multiple versioned rulebooks (e.g., competitive rules vs. casual rules, or expansions with rule modifications). The `corpus_version` field is already in the schema; the missing piece is an ingestion CLI flag for rulebook source and an API parameter to select which corpus version to query.

### Self-hosted LLM fallback

When the Gemini free tier is exhausted or unavailable, fall back to a self-hosted model (e.g., Llama 3.1 8B on a low-cost GPU instance or via Ollama). The generation isolation boundary in `backend/app/rag/generation.py` makes this a contained change — the pipeline does not need to know which model is running.
