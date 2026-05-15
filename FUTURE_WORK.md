# Future Work

Items in this file are deferred from v1. They are not aspirational — each entry is grounded in the existing codebase, the evaluation spec, or a concrete limitation observed during development. Items are grouped by approximate effort horizon.

---

## Short-term (1–2 weeks)

### Run the full ablation and publish numbers

The results table in the README currently shows TBD for all metric cells. The eval set (`Specs/03_eval_set_spec.md`) is defined; RAGAS is the framework. The blocking work is:

1. Execute Config A (vector-only baseline) against the eval set and record RAGAS scores + p95 latency
2. Execute Config B (hybrid dense + FTS + RRF, current production config) and compare
3. Fill the TBD cells in README and remove the disclaimer
4. Run a per-category failure analysis to validate or refute the entity resolution threshold (ADR-004)

### Streaming responses (SSE)

The current API returns a complete JSON response after the full generate call completes. This creates a perceptible pause for users. The fix is to stream the LLM response via Server-Sent Events from FastAPI and consume the stream in the Next.js frontend. The backend skeleton exists; the blocking piece is integrating SSE with the Upstash cache (cached responses should still stream, not return instantly, to avoid a jarring UX difference).

### Per-category failure analysis script

Add a script under `backend/scripts/` that reads an eval run JSON and breaks down failures by query category (factual, multi-step, card-specific, edge case, adversarial). This is a prerequisite for the entity resolution trigger check from ADR-004.

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
3. Run Config C eval and compare to Config B

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
