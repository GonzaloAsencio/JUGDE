# Riftbound Judge AI

An AI-powered rules judge for Riftbound TCG. Ask rules questions in plain language and get grounded answers with citations from the official rulebook.

![License](https://img.shields.io/badge/license-MIT-blue)

---

## What It Does

Riftbound Judge AI answers rules questions about the Riftbound trading card game by retrieving relevant passages from the official rulebook and using Gemini 2.0 Flash to generate a grounded, cited answer. The system refuses to speculate — if the retrieved context does not contain the answer, it defers rather than fabricates.

The project is built eval-first. Every architectural decision — embedding model, vector database, retrieval strategy — is tied to a measurable outcome. The evaluation spec defines 40–60 hand-curated question-answer pairs across five query categories: factual, multi-step, card-specific, edge case, and adversarial. Results are published once the eval runs are complete; no numbers appear in this README until they are measured.

---

## Architecture

```mermaid
graph TB
    subgraph Client
        User[Browser]
    end

    subgraph Frontend
        Next[Next.js 15 / Vercel]
        Proxy[API Proxy Route]
    end

    subgraph Backend
        API[FastAPI]
        RL[slowapi Rate Limiter]
        Cache[Upstash Redis Cache]
        Pipeline[RAG Pipeline]
    end

    subgraph Retrieval
        Embed[bge-m3 Query Encoder]
        VDB[(pgvector cosine ANN)]
        FTS[Postgres FTS plainto_tsquery]
        RRF[RRF Fusion rrf_k=60]
    end

    subgraph Generation
        LLM[Gemini 2.0 Flash]
    end

    subgraph Ingestion
        Corpus[rulebook.md + errata.md]
        IngestEmbed[bge-m3 Batch Encoder]
        Store[(pgvector + FTS index)]
    end

    subgraph Observability
        Langfuse[Langfuse Traces]
        Sentry[Sentry Errors]
    end

    User -->|HTTPS| Next
    Next --> Proxy
    Proxy -->|HTTP proxy| API
    API --> RL
    RL --> Cache
    Cache -->|cache hit| Next
    Cache -->|cache miss| Pipeline
    Pipeline --> Embed
    Embed --> VDB
    Embed --> FTS
    VDB --> RRF
    FTS --> RRF
    RRF --> LLM
    LLM --> Cache

    Corpus --> IngestEmbed
    IngestEmbed --> Store

    Pipeline -.->|traces| Langfuse
    API -.->|errors| Sentry
```

See [docs/architecture.md](docs/architecture.md) for a standalone version with narrative explanation.

---

## Tech Stack

| Technology | Role | Why |
|---|---|---|
| Python / FastAPI | API server | Async, Pydantic validation built-in |
| BAAI/bge-m3 | Embedding model | Free, local, multilingual-ready |
| Supabase / pgvector | Vector + FTS storage | Single DB for vectors, metadata, and full-text search |
| Gemini 2.0 Flash | LLM generation | Free tier (1M tok/day), fast, strong instruction following |
| Upstash Redis | Response cache | Serverless Redis — optional, disabled if env vars absent |
| Langfuse | LLM tracing | Per-request traces covering retrieval and generation |
| Sentry | Error reporting | Optional — disabled if DSN not set |
| Next.js 15 | Frontend | App Router, React 19, Vercel deployment |
| slowapi | Rate limiting | Per-IP limits: 10 req/min, 100 req/day |
| RAGAS | Eval framework | Faithfulness, answer relevancy, context precision/recall |

---

## Results

> **Eval status**: not yet run. All metric cells are TBD. Results will be published once RAGAS runs complete. See [FUTURE_WORK.md](FUTURE_WORK.md) for the timeline.

| Config | Faithfulness | Answer Relevancy | Context Precision | Context Recall | p95 Latency | Cost/query |
|---|---|---|---|---|---|---|
| A — Vector only (baseline) | TBD | TBD | TBD | TBD | TBD | TBD |
| B — Hybrid (dense + FTS + RRF) | TBD | TBD | TBD | TBD | TBD | TBD |
| C — Hybrid + Reranker | not implemented | not implemented | not implemented | not implemented | not implemented | not implemented |
| D — + Entity Resolution | not implemented | not implemented | not implemented | not implemented | not implemented | not implemented |

**Methodology**: Eval set size TBD. Evaluation framework: RAGAS. Latency measured server-side, excluding network. Cost computed from Gemini 2.0 Flash token pricing. Each configuration: mean of 3 independent runs.

---

## Key Decisions

The architecture reflects explicit tradeoffs documented as Architecture Decision Records. ADRs are the single source of truth for why things are the way they are — this section links to them rather than restating their content.

The most consequential decisions: choosing a local embedding model over a hosted API to eliminate per-query cost; keeping everything in a single Postgres instance to avoid dual-service complexity; switching from vector-only to hybrid retrieval after observing exact-token query failures in manual testing; and deferring entity resolution — there was no eval data to justify the complexity at v1.

- [ADR-001 — Embedding model: bge-m3 over OpenAI text-embedding-3-small](docs/adrs/ADR-001-embeddings.md)
- [ADR-002 — Vector database: pgvector on Supabase over dedicated vector DB](docs/adrs/ADR-002-vector-db.md)
- [ADR-003 — Retrieval strategy: hybrid dense + FTS + RRF over vector-only](docs/adrs/ADR-003-hybrid-retrieval.md)
- [ADR-004 — Entity resolution: deferred to v2 (data-driven decision)](docs/adrs/ADR-004-entity-resolution.md)
- [ADR-005 — LLM choice: Gemini 2.0 Flash over GPT-4o-mini and Claude Haiku](docs/adrs/ADR-005-llm-choice.md)

Full ADR index: [docs/adrs/README.md](docs/adrs/README.md)

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- A Supabase project with the `pgvector` extension enabled
- A Google AI Studio API key (free at [aistudio.google.com](https://aistudio.google.com))

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt        # runtime (correr la API)
pip install -r requirements-dev.txt    # + tests y scripts de corpus

cp .env.example .env
# Required: DATABASE_URL, GEMINI_API_KEY
# Optional: UPSTASH_REDIS_URL, UPSTASH_REDIS_TOKEN, LANGFUSE_*, SENTRY_DSN
# Optional: PROXY_SHARED_SECRET — locks the API to requests coming from the
#           Next.js proxy (required in production; leave unset for local dev)

# Ingest the corpus — first run downloads bge-m3 (~1.2 GB)
python -m scripts.ingest --source data/corpus/rulebook.md
python -m scripts.ingest --source data/corpus/errata.md

# Start the API
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install

cp .env.example .env.local
# Required: FASTAPI_URL=http://localhost:8000
# Production: PROXY_SHARED_SECRET — same value as the backend secret.
# Set it in BOTH Vercel and HF Spaces BEFORE deploying the backend change,
# otherwise every query returns 503.

npm run dev     # http://localhost:3000
```

### Eval

```bash
cd backend
# Eval runner script pending — see FUTURE_WORK.md
```

---

## Evaluation Methodology

The evaluation set was built manually, not generated by an LLM. Each question was written by a human, cross-referenced against the rulebook, and assigned a reference answer and the expected source section(s). LLM-generated questions were rejected because they tend to mirror document structure, which artificially inflates retrieval metrics.

The set is divided into five categories:

- **Factual**: single rule, direct lookup, high expected confidence
- **Multi-step**: requires synthesizing two or more rules from different sections
- **Card-specific**: keyword or ability lookup by exact card name — specifically designed to stress-test the FTS retrieval path
- **Edge case**: ambiguous or obscure rules where expected behavior is low confidence and a defer-to-judge response
- **Adversarial**: prompt injection attempts and off-topic queries — expected behavior is refusal or irrelevant citations

Metrics computed via RAGAS: Faithfulness (no hallucination), Answer Relevancy, Context Precision (retrieved chunks are relevant), Context Recall (correct chunks are retrieved). Latency is measured server-side from request receipt to response serialization. Cost is estimated from Gemini 2.0 Flash token pricing applied to actual prompt and completion token counts logged per request.

---

## What's Next

See [FUTURE_WORK.md](FUTURE_WORK.md) for the full deferred backlog, organized by horizon.

The immediate priority is running the baseline and hybrid eval configurations and publishing the results table. After that: streaming responses and the entity resolution data-collection pass.

---

## Credits

- **Rulebook data**: Riftbound official rulebook and errata documents
- **Embedding model**: [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) (MIT License)
- **Evaluation framework**: [RAGAS](https://github.com/explodinggradients/ragas) (Apache 2.0)
- **Vector search**: [pgvector](https://github.com/pgvector/pgvector) (PostgreSQL License)
- **Tracing**: [Langfuse](https://langfuse.com) (MIT License)

License: MIT — see [LICENSE](LICENSE).
