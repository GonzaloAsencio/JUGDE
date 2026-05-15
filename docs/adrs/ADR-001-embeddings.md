# ADR-001 — Embedding Model: bge-m3 over OpenAI text-embedding-3-small

**Status**: Accepted  
**Date**: 2026-05-15  
**Authors**: Gonzalo Asencio

---

## Context

The RAG pipeline needs to encode both the rulebook corpus (at ingestion time) and user queries (at request time) into dense vector representations. The choice of embedding model determines retrieval quality, operating cost, and deployment complexity.

The corpus is English-only in v1, but the Riftbound rulebook may expand to Spanish and other languages as the game grows internationally. The pipeline must be cost-sustainable for a side project running on a free tier.

Candidates evaluated:
- `BAAI/bge-m3` — multilingual model from BAAI, available on Hugging Face, runs locally
- `text-embedding-3-small` — OpenAI's hosted embedding API, 1536 dimensions
- `Cohere Embed v3` — Cohere's hosted embedding API

---

## Decision

Use `BAAI/bge-m3` loaded locally via `sentence-transformers`.

The model is configured in `backend/app/config.py` as `model_name: str = "BAAI/bge-m3"` with `embedding_dim: int = 1024`.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| `text-embedding-3-small` | Paid API — adds per-query cost and a network dependency at request time. Ingestion cost grows with corpus size. |
| `Cohere Embed v3` | Also paid, introduces a second third-party dependency alongside Gemini. |
| `text-embedding-3-large` | Higher quality but higher cost; not justified for a free-tier project. |

---

## Consequences

✅ Zero embedding cost — no API key or billing account required for embeddings.  
✅ No network dependency during retrieval — embeddings are computed locally at query time.  
✅ Multilingual-ready — bge-m3 supports 100+ languages without retraining, important for future Spanish localization.  
✅ 1024-dimension output is a good balance between quality and storage/index size.  

❌ Cold start latency — the model takes approximately 3–5 seconds to load on first startup, adding to the initial boot time.  
❌ Memory footprint — bge-m3 requires approximately 1.2 GB RAM at runtime, which constrains deployment on small free-tier instances.  
❌ HF revision must be pinned in production to avoid silent quality regressions on model updates.  
❌ Local CPU inference is slower than a batched GPU API — ingestion of a large corpus is significantly slower than with a hosted API.
