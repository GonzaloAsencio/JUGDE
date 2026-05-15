# ADR-003 — Retrieval Strategy: Hybrid Dense + FTS + RRF over Vector-Only

**Status**: Accepted  
**Date**: 2026-05-15  
**Authors**: Gonzalo Asencio

---

## Context

The initial retrieval implementation used pure dense vector search (cosine similarity via pgvector). During testing, queries containing exact token sequences — card names like "Quick Strike", rule identifiers like "Section 4.2", and errata references — returned irrelevant chunks even when the rulebook contained a verbatim match. Dense embeddings are semantic; they generalize well but can miss exact-string matches when a rare term has low embedding similarity to the query representation.

The problem was not the LLM. The LLM was never seeing the right chunks. The model wasn't lying — the retriever was.

Two retrieval signals were available without adding infrastructure: the existing pgvector index for dense similarity, and Postgres full-text search (FTS) via `to_tsvector` / `plainto_tsquery`.

Candidates evaluated:
- Vector-only (cosine similarity, top-k=5)
- FTS-only (BM25-equivalent ts_rank_cd, top-k=5)
- Hybrid: dense + FTS fused with Reciprocal Rank Fusion (RRF)
- Weighted score fusion (linear combination of cosine similarity and FTS rank)

---

## Decision

Use hybrid retrieval: fetch `top_k_fetch=15` results from each signal independently, then fuse with Reciprocal Rank Fusion (RRF) and return the top `top_k=5` results.

**RRF formula**: For each chunk `d`, the fused score is the sum of `1 / (rrf_k + rank_l(d))` across each result list `l` where `d` appears, where `rank_l(d)` is the 1-based position of the chunk in that list. Configuration: `rrf_k=60` (standard constant from the original RRF paper — smooths the contribution of low-ranked results).

Tie-break rule: when two chunks have equal RRF score, the chunk from the vector list wins. This preserves semantic relevance as the default signal.

Implementation: `backend/app/rag/retrieval.py` — `_rrf_fuse()`, called by `hybrid_search` which is exposed through `observe_or_noop` for Langfuse tracing.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| Vector-only | Exact-token queries (card names, rule numbers) fail when the embedding model does not preserve rare-term identity. Observed in manual testing before eval set was formalized. |
| FTS-only | Semantic paraphrase queries fail — "can I block the turn a unit is played" would not match "summoning sickness" if the rulebook uses different phrasing. |
| Weighted score fusion | Requires normalizing cosine similarity (0–1) and ts_rank_cd (unitless, unbounded) onto a common scale. Score normalization is brittle and easy to miscalibrate. RRF uses only rank position — no normalization needed. |

---

## Consequences

✅ Covers both query types: semantic paraphrases (dense) and exact-token lookups (FTS). The two signals complement each other rather than competing.  
✅ RRF is robust to score-scale differences — rank position is signal-agnostic, so adding a third retrieval signal later requires no retuning of weights.  
✅ Chunks that appear in both result lists receive a score bonus — the most relevant chunks tend to surface from both signals simultaneously.  
✅ No new infrastructure — both queries go to the same Postgres instance already in use.  

❌ Two queries per request instead of one — approximately 20% latency increase compared to vector-only on the retrieval step.  
❌ The tie-break logic (vector wins) is easy to misread: it does not mean vector is always "better", only that it is the default signal when RRF scores are identical.  
❌ `top_k_fetch=15` means 30 rows are fetched from Postgres before being trimmed to 5 — higher network bytes per request.
