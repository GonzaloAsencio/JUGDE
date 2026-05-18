# Proposal: Production Hardening

## Intent

The Riftbound Judge AI demo is functionally complete but fragile: no rate limiting (free-tier abuse risk), no caching (repeated identical queries burn LLM tokens), no tracing/error visibility (blind in prod), weak input validation (prompt injection / XSS risk), and no graceful frontend error states. Before sharing the demo publicly, we need a single coordinated hardening pass that protects free-tier budgets, gives us observability, and makes the system resilient to abuse and transient failures.

## Scope

### In Scope
- Redis (Upstash) response cache keyed by hash(normalized_query + card_mentions), TTL 24h
- IP-based rate limiting via `slowapi`: 10 req/min and 100 req/day, returning 429 + `Retry-After`
- Langfuse end-to-end tracing (retrieval, LLM, latency, tokens, cost, cache hits)
- Sentry error tracking for 5xx only, 10% sample rate, 4xx ignored
- Pydantic input validation: `question` 3-500 chars, max 10 `card_mentions`, reject XSS-like patterns
- Prompt-injection defense: hardened system prompt + post-generation validation (no system prompt leakage, no hallucinated citations)
- Frontend error states for 429, 5xx, network, and timeout (>10s)
- `structlog` JSON logging with `query_id`, `latency_ms`, `tokens_used`, `cache_hit`, `confidence`
- `GET /health` (shallow) and `GET /health/deep` (DB, Redis, LLM probes)

### Out of Scope
- User authentication / per-user quotas (IP-based only for now)
- Multi-region failover / autoscaling
- Cache invalidation on corpus updates (manual flush acceptable for demo)
- Distributed tracing across services beyond Langfuse spans
- WAF / DDoS protection beyond rate limiting

## Capabilities

### New Capabilities
- `response-cache`: Redis-backed response caching with deterministic key derivation and TTL
- `rate-limiting`: per-IP request throttling with standard 429 semantics
- `observability`: Langfuse tracing, Sentry error capture, structured JSON logs
- `input-validation`: Pydantic-level question/mention validation and injection rejection
- `prompt-injection-defense`: system prompt hardening + post-generation safety checks
- `frontend-error-states`: typed UI handling for 429 / 5xx / network / timeout
- `health-checks`: shallow + deep health endpoints

### Modified Capabilities
- None (no prior openspec specs exist; this change establishes the baseline)

## Approach

Single coordinated PR layered top-down: (1) middleware (rate limit, Sentry, structlog) wraps FastAPI app in `main.py`; (2) cache + Langfuse tracing wrap the RAG pipeline in `rag/pipeline.py`; (3) Pydantic validators tighten the request model; (4) prompt hardening + post-gen validation live inside the LLM call boundary; (5) health endpoints added as standalone routes; (6) frontend adds a typed error mapper in `lib/api.ts` and updates components to render error variants. External services (Upstash, Langfuse, Sentry) are configured via env vars with safe no-op fallbacks when keys are missing, so local dev keeps working.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/main.py` | Modified | Wire slowapi, Sentry, structlog, health routes |
| `backend/app/rag/pipeline.py` | Modified | Cache lookup/store, Langfuse spans, post-gen validation |
| `backend/app/rag/retrieval.py` | Modified | Langfuse span around retrieval |
| `backend/app/schemas.py` (new/existing) | Modified | Pydantic validators for `question`, `card_mentions` |
| `backend/app/cache.py` (new) | New | Upstash Redis client + key derivation |
| `backend/app/observability.py` (new) | New | Langfuse + Sentry + structlog init |
| `backend/app/health.py` (new) | New | Shallow + deep health routes |
| `backend/requirements.txt` | Modified | Add slowapi, redis, langfuse, sentry-sdk, structlog |
| `frontend/lib/api.ts` | Modified | Typed error mapping + 10s timeout |
| `frontend/components/*` | Modified | Render 429/5xx/network/timeout states |
| `.env.example` | Modified | Document new env vars |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Cache returns stale answer after corpus update | Med | Manual flush endpoint + TTL 24h cap |
| Rate limit blocks legitimate demo audience behind shared NAT | Med | Generous 10/min + 100/day; document override env var |
| Langfuse / Sentry / Redis outage breaks request path | Low | No-op fallbacks; observability is best-effort, never blocking |
| Prompt-injection post-validation false-positives reject good answers | Med | Conservative checks (system-prompt leakage, fabricated citation IDs only) + log instead of fail on borderline |
| Single large PR hard to review | High | Accepted under `single-pr` delivery strategy; reviewer guidance in PR description by subsystem |

## Rollback Plan

All new behavior is feature-flagged via env vars (`REDIS_URL`, `LANGFUSE_PUBLIC_KEY`, `SENTRY_DSN`, `RATE_LIMIT_ENABLED`). Unsetting them disables the corresponding subsystem at startup with a logged warning. Full rollback = revert the PR commit; no schema migrations, no data writes beyond cache (ephemeral). Frontend error states degrade gracefully — old backend without new error codes still works.

## Dependencies

- Upstash Redis account + REST URL/token
- Langfuse Cloud account + public/secret keys
- Sentry project DSN
- Python deps: `slowapi`, `redis`, `langfuse`, `sentry-sdk[fastapi]`, `structlog`

## Success Criteria

- [ ] Cache hit rate >40% on a 50-query replay of common questions
- [ ] Rate limit returns 429 + `Retry-After` after 10 req/min from same IP
- [ ] Every query produces one Langfuse trace with retrieval+LLM spans, tokens, and cost
- [ ] Sentry receives only 5xx events; 4xx noise stays out
- [ ] Invalid inputs (too short, too long, >10 mentions, XSS pattern) return 422 with clear message
- [ ] Prompt-injection test suite (system-prompt leak attempts, fake citation injection) blocked or sanitized
- [ ] Frontend renders distinct UI for 429, 5xx, network failure, and >10s timeout
- [ ] `/health` returns 200 in <50ms; `/health/deep` reports per-dependency status
- [ ] Structured JSON logs contain `query_id`, `latency_ms`, `tokens_used`, `cache_hit`, `confidence` on every request
