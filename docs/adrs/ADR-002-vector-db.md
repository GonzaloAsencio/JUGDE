# ADR-002 — Vector Database: pgvector on Supabase over Dedicated Vector DB

**Status**: Accepted  
**Date**: 2026-05-15  
**Authors**: Gonzalo Asencio

---

## Context

The RAG pipeline stores 1024-dimensional embeddings for all corpus chunks and performs approximate nearest-neighbor (ANN) queries at request time. The system also needs full-text search (FTS) over the same chunks for the hybrid retrieval strategy (see ADR-003).

Options were evaluated along three axes: operational overhead, cost, and ability to run SQL alongside vector queries.

Candidates evaluated:
- `pgvector` on Supabase — Postgres extension for vector similarity, hosted on Supabase free tier
- `Pinecone` — managed dedicated vector database
- `Qdrant Cloud` — managed dedicated vector database
- `FAISS` — local in-process ANN library

---

## Decision

Use `pgvector` hosted on Supabase. The application connects via `psycopg2` using a connection pool (`SimpleConnectionPool`). Vector queries use the `<=>` cosine distance operator. FTS queries use Postgres `to_tsvector` / `plainto_tsquery`.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| Pinecone | Paid after free tier. Does not provide FTS — would require a second database for full-text search, doubling operational complexity. |
| Qdrant Cloud | Free tier available but adds a second service to manage. No native FTS; would still need Postgres or Elasticsearch alongside it. |
| Local FAISS | No persistence — index is lost on restart. No FTS support. Not viable for a deployed service. |

---

## Consequences

✅ Single database — chunks, embeddings, metadata, and FTS index all live in one Postgres instance. No dual-service complexity.  
✅ SQL joins available — metadata filtering (e.g., `corpus_version`) is a WHERE clause, not a separate filtering step.  
✅ Supabase free tier covers the corpus size for v1 — no billing required.  
✅ Postgres FTS (`to_tsvector` / `plainto_tsquery`) enables the hybrid retrieval strategy without adding infrastructure.  

❌ pgvector uses an IVFFLAT or HNSW index which is not as optimized for ANN at large scale compared to dedicated vector databases — at 10M+ chunks this would require careful index tuning.  
❌ Latency is bound by Postgres connection overhead — every query goes through a TCP connection (mitigated by the connection pool, but not zero-cost).  
❌ Supabase free tier has connection limits — connection pool size must stay conservative.
