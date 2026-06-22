# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for the Riftbound Judge AI project. Each ADR documents a significant technical decision: the context that drove it, the choice made, alternatives that were considered, and the honest tradeoffs.

ADRs are the single source of truth for architectural decisions. The main README links to these by ID and never restates their content.

---

## Index

### [ADR-001 — Embedding Model: bge-m3 over OpenAI text-embedding-3-small](ADR-001-embeddings.md)

The project uses `BAAI/bge-m3` loaded locally via `sentence-transformers` instead of a hosted embedding API. The decision was driven by zero embedding cost, no network dependency at query time, and multilingual readiness for future localization. The main tradeoffs are a cold-start delay of 3–5 seconds and approximately 1.2 GB RAM consumption.

---

### [ADR-002 — Vector Database: pgvector on Supabase over Dedicated Vector DB](ADR-002-vector-db.md)

The project stores chunk embeddings in a Postgres database (Supabase) using the `pgvector` extension rather than a dedicated vector database like Pinecone or Qdrant. The key benefit is a single database for vectors, metadata, and full-text search — no dual-service complexity. The tradeoff is that Postgres ANN performance does not match dedicated vector databases at large scale, and connection overhead adds a latency floor.

---

### [ADR-003 — Retrieval Strategy: Hybrid Dense + FTS + RRF over Vector-Only](ADR-003-hybrid-retrieval.md)

The pipeline uses hybrid retrieval — dense vector search fused with Postgres full-text search via Reciprocal Rank Fusion (RRF, rrf_k=60) — rather than pure vector search. This was added after observing that exact-token queries (card names, rule identifiers) failed with vector-only retrieval. The cost is approximately 20% higher retrieval latency due to two database queries per request.

---

### [ADR-004 — Entity Resolution: Deferred to v2 (Data-Driven Decision)](ADR-004-entity-resolution.md)

Card-specific entity resolution (detecting card names in queries and injecting card text into the prompt) was intentionally not built in v1. The decision was data-driven: without eval numbers showing card-specific failure rates above the defined 20% threshold, building entity resolution optimizes for a hypothesis rather than a measured problem. A forward hook (`card_mentions` parameter) is already wired through the pipeline for future implementation.

---

### [ADR-005 — LLM Choice: Gemini 2.0 Flash over GPT-4o-mini and Claude Haiku](ADR-005-llm-choice.md)

The generation step uses `gemini-2.0-flash` via Google AI Studio. The decision was cost-driven: Gemini offers a 1 million token per day free tier, making it viable for a free-tier project with open demo access. The LLM call is isolated in `backend/app/rag/generation.py` to allow model swaps without touching the pipeline. The main risks are rate limiting under sustained traffic and Google's free tier terms.

---

### [ADR-006 — Eval Framework: LLM-as-Judge over RAGAS](ADR-006-eval-framework.md)

The evaluation harness (`backend/scripts/eval.py`, `eval_judge.py`) uses a self-contained LLM-as-judge (verdict: correct/partial/wrong) plus deterministic retrieval recall, instead of the RAGAS framework originally planned in `Specs/03` and `Specs/06`. The decision was driven by prioritization — eval was built last, and a dependency-light harness reusing the existing LLM provider got a measured baseline fastest. The tradeoff is coarser metrics and no measured faithfulness; RAGAS remains optional future work. Supersedes the eval plan in those specs.
