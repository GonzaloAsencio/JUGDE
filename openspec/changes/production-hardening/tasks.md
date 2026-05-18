# Tasks: Production Hardening

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 550–700 |
| 400-line budget risk | High |
| Chained PRs recommended | No |
| Suggested split | Single PR with `size:exception` |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | All production hardening (7 subsystems) | PR 1 | `size:exception` — cross-cutting; splitting yields integration risk |

---

## Phase 1: Setup — Dependencies, Config, Env

- [ ] 1.1 Add `upstash-redis`, `slowapi`, `langfuse`, `sentry-sdk[fastapi]`, `structlog` to `backend/requirements.txt`
- [ ] 1.2 Add new settings fields to `backend/app/config.py`: `app_env`, `upstash_redis_url`, `upstash_redis_token`, `langfuse_secret_key`, `langfuse_public_key`, `langfuse_host`, `sentry_dsn`, `sentry_sample_rate=0.1`, `rate_limit_enabled=True`, `rate_limit_per_min=10`, `rate_limit_per_day=100`, `cache_ttl_s=86400`
- [ ] 1.3 Create/update `.env.example` documenting all new env vars with placeholder values and inline comments
- [ ] 1.4 **Commit**: `feat(hardening): setup — deps, config, env vars`

## Phase 2: Cache

- [ ] 2.1 Create `backend/app/cache.py` with async `get_cached(key)`, `set_cached(key, value, ttl)`, `make_cache_key(question, corpus_version)` using SHA-256 of normalized question + corpus_version; include no-op fallback when Redis unreachable
- [ ] 2.2 Attach `app.state.redis` client in `backend/app/main.py` lifespan startup; close on shutdown
- [ ] 2.3 **Commit**: `feat(hardening): cache — upstash redis client + key derivation`

## Phase 3: Rate Limiting

- [ ] 3.1 Create `backend/app/middleware/__init__.py` (package marker)
- [ ] 3.2 Create `backend/app/middleware/rate_limit.py` with slowapi `Limiter`, IP key func, and `_rate_limit_exceeded_handler`; guard all logic under `settings.rate_limit_enabled`
- [ ] 3.3 Wire into `backend/app/main.py`: attach `app.state.limiter`, mount `SlowAPIMiddleware`, register `RateLimitExceeded` exception handler with `Retry-After` header
- [ ] 3.4 Apply `@limiter.limit(...)` decorator to `POST /api/v1/query` in `backend/app/api/v1/query.py` (10/min, 100/day); leave `/health` and feedback exempt
- [ ] 3.5 **Commit**: `feat(hardening): rate-limiting — slowapi middleware + query endpoint limits`

## Phase 4: Observability

- [ ] 4.1 Create `backend/app/observability.py`: `init_observability(settings)` initializing Sentry (ASGI, `before_send` filter for 4xx), Langfuse client (or None), and structlog (JSON in prod, console in dev based on `app_env`); expose `get_logger(name)` and module-level `langfuse_client`
- [ ] 4.2 Call `sentry_sdk.init(...)` at top of `backend/app/main.py` before `FastAPI()`, gated by `settings.sentry_dsn`
- [ ] 4.3 Call `init_observability(settings)` inside lifespan startup in `backend/app/main.py`; replace stdlib `logging` calls with structlog
- [ ] 4.4 Add `@observe(name="retrieval")` (or local `observe_or_noop` wrapper) to `hybrid_search` / retrieval entry point in `backend/app/rag/retrieval.py`
- [ ] 4.5 **Commit**: `feat(hardening): observability — sentry, langfuse, structlog`

## Phase 5: Input Validation + Prompt Injection Defense

- [ ] 5.1 Update `QueryRequest` in `backend/app/rag/schemas.py`: `question` min=3/max=500, `@field_validator` rejecting `<script`, `javascript:`, `on\w+=` patterns (HTTP 422); `card_mentions: list[str]` max 10 items each max 100 chars; `language: Literal["en","es"] = "en"`; `session_id: Optional[str]` max 64 chars
- [ ] 5.2 Add `HARDENED_SYSTEM_PROMPT` segment to `backend/app/rag/generation.py` (refuse prompt disclosure, refuse role changes, refuse off-topic); add `post_gen_validate(answer, citations) -> (answer, was_sanitized)` replacing response if it contains "system prompt" (case-insensitive), stripping citations with non-existent `chunk_id`
- [ ] 5.3 **Commit**: `feat(hardening): input-validation + prompt-injection defense`

## Phase 6: Pipeline Integration (Cache + Tracing + Post-gen)

- [ ] 6.1 Update `backend/app/rag/pipeline.py` `answer_question` body: bind structlog `query_id` (UUID), check cache (return early with `cache_hit=True`), wrap generation in Langfuse trace (retrieval span + generation span capturing `latency_ms`, `tokens_used`, `model`), call `post_gen_validate`, `set_cached` on success, emit `structlog.info("query.complete", query_id, latency_ms, tokens, cache_hit)`
- [ ] 6.2 **Commit**: `feat(hardening): pipeline integration — cache + tracing + post-gen validation`

## Phase 7: Health Checks

- [ ] 7.1 Create `backend/app/health.py` with `router = APIRouter()`; `GET /health` returns `{status, version, corpus_version, timestamp}` in <50ms (no I/O); `GET /health/deep` probes DB (`SELECT 1`), Redis (`PING`), Gemini liveness — returns `{status: "ok"|"degraded", checks: {db, redis, llm}}` HTTP 200 in all cases, catches all exceptions
- [ ] 7.2 Register `health.router` in `backend/app/main.py`; ensure both routes are excluded from slowapi limiter
- [ ] 7.3 **Commit**: `feat(hardening): health checks — shallow + deep endpoints`

## Phase 8: Frontend Error States

- [ ] 8.1 Add `ErrorType = 'rate_limit' | 'timeout' | 'server' | 'network' | 'validation' | 'unknown'` and `ApiError` class to `frontend/lib/types.ts`
- [ ] 8.2 Update `frontend/lib/api.ts`: add `mapError(res, body) -> { type: ErrorType, message, retryAfter? }`, add 10s `AbortController` timeout, throw `ApiError` on 429/5xx/timeout/network; ensure `Retry-After` header is forwarded from `frontend/app/api/query/route.ts`
- [ ] 8.3 Update `frontend/store/useQueryStore.ts`: change `error` field from `string | null` to `{ type: ErrorType, message: string, retryAfter?: number } | null`; catch `ApiError` in `submit()` and set typed payload
- [ ] 8.4 Create `frontend/components/ErrorDisplay.tsx`: branch on `error.type` rendering rate-limit message (with `retryAfter` seconds), 5xx message, timeout message, network message, validation message — each variant includes a retry button
- [ ] 8.5 Wire `ErrorDisplay` into `frontend/components/AnswerDisplay.tsx` (or the relevant page component) so it renders when `error !== null`
- [ ] 8.6 **Commit**: `feat(hardening): frontend error states — typed errors + ErrorDisplay component`

## Phase 9: Tests

- [ ] 9.1 Write `backend/tests/test_cache.py`: unit test `make_cache_key` normalizes casing + strips whitespace (spec: normalization scenario); test graceful degradation when Redis returns exception
- [ ] 9.2 Write `backend/tests/test_validation.py`: unit test `QueryRequest` rejects `question` <3 chars (HTTP 422), rejects `<Script>` pattern (HTTP 422), accepts valid input, rejects >10 `card_mentions`, rejects `language="fr"`
- [ ] 9.3 Write `backend/tests/test_health.py`: test `GET /health` returns 200 with 4 required fields; test `GET /health/deep` returns 200 with `status="degraded"` when Redis probe fails
- [ ] 9.4 Write `backend/tests/test_rate_limit.py`: integration test — send 11 requests to `POST /api/v1/query` in test client; assert 11th returns 429 with `Retry-After` header; assert `GET /health` returns 200 after limit exceeded (spec: exempt endpoints scenario)
- [ ] 9.5 Write `backend/tests/test_prompt_injection.py`: unit test `post_gen_validate` replaces response containing "system prompt"; test clean response passes through unchanged; test citation with non-existent `chunk_id` is stripped
- [ ] 9.6 **Commit**: `test(hardening): unit + integration tests for all subsystems`
