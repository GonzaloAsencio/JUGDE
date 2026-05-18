# Design: Production Hardening

## 1. Architectural Approach

**Pattern**: Layered middleware + decorator wrapping around an unchanged core pipeline.

The existing FastAPI app is a thin orchestrator (`main.py` lifespan → `query.py` route → `pipeline.answer_question` → retrieval + Gemini). Hardening is added as **concentric rings** around that core:

```
[ Request ]
  -> Sentry ASGI middleware       (captures unhandled 5xx)
  -> slowapi rate-limit middleware (429 + Retry-After)
  -> FastAPI router
       -> Pydantic validators      (422 on bad input)
       -> route handler
            -> cache.get(key)      (HIT -> return)
            -> langfuse @observe   (trace span)
                 -> answer_question(...) UNCHANGED CORE
            -> cache.set(key, value, ttl=24h)
            -> post-gen validation (citation / leak guard)
       -> structlog binds query_id, latency, tokens, cache_hit
  -> Response
```

Core RAG logic (`answer_question`, `hybrid_search`, `call_gemini`) is **not restructured**. Cache, tracing, and validation are bolt-on layers. This keeps the change low-risk and makes every new subsystem independently disable-able via env var.

**Frontend** mirrors this: existing components stay; a typed error mapper in `lib/api.ts` and an `errorType` discriminant in the Zustand store let components branch on error variants without refactoring the happy path.

## 2. Component Map

### Backend — new modules

| File | Responsibility | Public surface |
|---|---|---|
| `backend/app/cache.py` | Upstash Redis async client + key derivation + no-op fallback when `UPSTASH_REDIS_URL` missing | `async get_cached(key) -> dict \| None`, `async set_cached(key, value, ttl)`, `make_cache_key(question, corpus_version) -> str` |
| `backend/app/observability.py` | Initializes Sentry, Langfuse client, structlog (JSON in prod, console in dev). Graceful no-ops when keys absent. | `init_observability(settings)`, `get_logger(name)`, `langfuse_client` (module-level, may be `None`) |
| `backend/app/health.py` | Routes `GET /health` (shallow) and `GET /health/deep` (DB+Redis+LLM probe) | `router = APIRouter()` |
| `backend/app/middleware/__init__.py` | Empty package marker | — |
| `backend/app/middleware/rate_limit.py` | slowapi `Limiter` instance, key func, exception handler | `limiter`, `rate_limit_exceeded_handler` |

### Backend — modified modules

| File | Change |
|---|---|
| `backend/app/main.py` | (a) Top-of-file `sentry_sdk.init(...)` before `FastAPI(...)`; (b) `init_observability(settings)` inside lifespan; (c) attach `app.state.limiter`, mount slowapi exception handler, add `SlowAPIMiddleware`; (d) include `health.router`; (e) replace stdlib `logging.basicConfig` with structlog config; (f) attach `app.state.redis = await build_cache(settings)`; close on shutdown. |
| `backend/app/config.py` | Add fields: `app_env: Literal["dev","staging","prod"]="dev"`, `upstash_redis_url: str \| None`, `upstash_redis_token: str \| None`, `langfuse_secret_key: str \| None`, `langfuse_public_key: str \| None`, `langfuse_host: str = "https://cloud.langfuse.com"`, `sentry_dsn: str \| None`, `sentry_sample_rate: float = 0.1`, `rate_limit_enabled: bool = True`, `rate_limit_per_min: int = 10`, `rate_limit_per_day: int = 100`, `cache_ttl_s: int = 86400`. |
| `backend/app/rag/schemas.py` | Tighten `QueryRequest`: `question` 3-500 chars (was 1000), add `@field_validator` rejecting XSS patterns (`<script`, `javascript:`, `on\w+=`), add optional `card_mentions: list[str] = Field(default_factory=list, max_length=10)` with per-item length cap. |
| `backend/app/rag/pipeline.py` | Wrap `answer_question` body: bind structlog query_id, check cache (return early on hit with `cache_hit=True`), run existing logic inside Langfuse trace context (retrieval span + generation span), call `post_gen_validate(answer, citations)` before return, write to cache on success. |
| `backend/app/rag/generation.py` | Add `HARDENED_SYSTEM_PROMPT` segment (refuse to disclose system prompt, refuse to invent citations) and `post_gen_validate(answer, citations) -> (answer, was_sanitized)` helper. |
| `backend/app/rag/retrieval.py` | Add `@observe(name="retrieval")` decorator (no-op when Langfuse disabled). |
| `backend/app/api/v1/query.py` | Apply `@limiter.limit(...)` decorator; existing exception handlers untouched. |
| `backend/requirements.txt` | Add `upstash-redis`, `slowapi`, `langfuse`, `sentry-sdk[fastapi]`, `structlog`. |
| `.env.example` | Document new vars. |

### Frontend — modified modules

| File | Change |
|---|---|
| `frontend/lib/api.ts` | Add `mapError(res, body) -> { type: ErrorType, message, retryAfter? }` where `ErrorType = 'rate_limit' \| 'timeout' \| 'server' \| 'network' \| 'validation' \| 'unknown'`. Add 10s `AbortController` timeout. Throw typed `ApiError`. |
| `frontend/lib/types.ts` | Export `ErrorType`, `ApiError`. |
| `frontend/store/useQueryStore.ts` | Replace `error: string \| null` with `error: { type: ErrorType, message: string, retryAfter?: number } \| null`. Catch `ApiError` in `submit()` and set typed payload. |
| `frontend/components/AnswerDisplay.tsx` (or new `ErrorDisplay.tsx`) | Branch on `error.type` to render 429 (with Retry-After countdown), 5xx, timeout, network, validation variants. |

Frontend has **no new dependencies** — countdown timer uses `setInterval` inside a `useEffect`.

## 3. Data Flow

### Hot path (cache miss)
```
client -> /api/query (Next.js route) -> FastAPI /api/v1/query
   slowapi check (IP -> bucket)              [might 429 here]
   Pydantic validate (length, XSS regex)     [might 422 here]
   cache_key = sha256(normalize(question) + corpus_version)
   redis.get(cache_key)  -> miss
   langfuse trace start
     embedder.encode -> hybrid_search -> build_prompt -> call_gemini
   langfuse trace end (spans: retrieval, generation; metadata: tokens, cost)
   post_gen_validate(answer, citations)
   redis.set(cache_key, response_json, EX=86400)
   structlog.info("query.complete", query_id, latency_ms, tokens, cache_hit=False)
   return 200 JSON
```

### Hot path (cache hit)
```
client -> ... -> Pydantic validate -> redis.get(cache_key) -> HIT
structlog.info("query.complete", cache_hit=True, latency_ms<5)
return 200 JSON (skip langfuse, skip generation)
```

### Health
```
GET /health        -> 200 {"status":"ok"} (no I/O, <5ms)
GET /health/deep   -> probe DB (SELECT 1), Redis (PING), Gemini (cached state.gemini_client liveness)
                      -> 200 with per-dep status, or 503 if any required dep down
```

## 4. Integration Points & Boundaries

- **Upstash Redis**: HTTP-based REST client (`upstash-redis`), no TCP pool needed, safe across Vercel/serverless. Constructed lazily from env in `cache.py`. **Failure mode**: log warning, return `None` for `get_cached`, no-op for `set_cached`. Request continues without caching.
- **Langfuse**: SDK runs spans in background flush queue. `@observe` decorator wraps functions; when client is `None`, decorator is a pass-through (we ship a local `observe_or_noop` wrapper to avoid hard import errors when key missing). **Failure mode**: warnings logged, request unaffected.
- **Sentry**: ASGI middleware only captures unhandled exceptions and 5xx responses (`before_send` filters out 4xx). `sample_rate=0.1`, `traces_sample_rate=0.0` (we use Langfuse for traces). **Failure mode**: Sentry init catches its own errors; bad DSN = warning, app continues.
- **slowapi**: in-memory limiter for v1 (single-instance backend). Future: swap to Redis backend via `storage_uri`. Key func is `get_remote_address` (respects `X-Forwarded-For` when behind proxy via `proxy_headers=True` on uvicorn).

All three external services are **observability/optimization, never on the critical path**. The system answers questions correctly even with Redis, Langfuse, and Sentry all unavailable.

## 5. Architectural Decisions (ADR-style)

### ADR-1: Cache placement — after rate limit, before retrieval

**Decision**: Cache lookup happens after Pydantic validation and after slowapi check, inside the route handler / pipeline entry.

**Rationale**: Rate limit must guard the cache too (otherwise an attacker can hammer the cache lookup itself, and we lose the abuse-protection signal in logs). Cache must short-circuit before the expensive embedder + DB + Gemini path. Validation runs first because rejecting malformed input before cache key derivation prevents cache pollution.

**Rejected**: (a) Cache as middleware before rate limit — would let unlimited cached responses through, defeating per-IP budget enforcement and producing misleading rate-limit telemetry. (b) Cache inside `hybrid_search` only — misses the LLM call, which is 95% of the cost.

### ADR-2: Langfuse via try/except wrapper, never blocking

**Decision**: A local `observe_or_noop` decorator wraps `@langfuse.decorators.observe`. When `langfuse_client is None` or import fails, it returns the original function. Inside the decorator, exceptions from Langfuse calls are caught and logged at WARNING; the wrapped function's return value is propagated regardless.

**Rationale**: Observability tooling that takes down production is worse than no observability. Langfuse cloud has occasional 5xx; we will not couple our SLO to theirs. Same approach as Sentry's design.

**Rejected**: Direct `@observe` from the SDK — its failure modes include network timeouts and serialization errors that would propagate to the caller. Verified by reading Langfuse SDK source: decorators do swallow some errors but not all (e.g., flush queue overflow can raise).

### ADR-3: Sentry init at module top, before `FastAPI(...)`

**Decision**: `sentry_sdk.init(...)` runs at import time of `main.py`, before any `FastAPI` instance exists, gated by `settings.sentry_dsn`.

**Rationale**: Sentry must capture import-time errors (bad config, missing env vars) and lifespan startup errors. If init is inside the lifespan context manager, a crash during DB pool init or embedder load would not be reported. The pattern is standard FastAPI+Sentry integration.

**Rejected**: Init inside lifespan — misses startup failures, which are the highest-signal errors.

### ADR-4: structlog — JSON in prod, console renderer in dev, keyed by APP_ENV

**Decision**: `init_observability` configures structlog processors based on `settings.app_env`. `app_env=prod` -> `JSONRenderer`. `app_env in {dev, staging}` -> `ConsoleRenderer(colors=True)`. Standard library logging is routed through structlog via `foreign_pre_chain`.

**Rationale**: Prod log aggregators (Vercel logs, Datadog) need structured JSON for indexing query_id, latency, tokens. Dev needs human-readable colored output for fast iteration. APP_ENV is the explicit switch; not auto-detecting via `sys.stdout.isatty()` because Docker dev can produce a TTY and still want JSON.

**Rejected**: stdlib logging with a custom JSON formatter — works but loses structlog's contextvar-based query_id propagation across async boundaries.

### ADR-5: Validation tightening — Pydantic field validators, not middleware

**Decision**: XSS-pattern rejection (`<script`, `javascript:`, `on\w+=`) lives in `QueryRequest` `@field_validator`, not in a request middleware.

**Rationale**: Validation errors should return 422 with field-level error messages so the frontend can render targeted feedback. Middleware-level rejection returns 400 with a generic message and bypasses Pydantic's serialization, costing us frontend UX. The validator runs on the typed model after parsing, which is the FastAPI canonical layer for input rules.

**Rejected**: ASGI middleware doing regex on raw body — costs more (re-parsing JSON), loses field-level error context, harder to test.

### ADR-6: Frontend error model — discriminated union in store, not stringly-typed

**Decision**: `error` field in Zustand store is `{ type: ErrorType, message: string, retryAfter?: number } | null`, where `ErrorType` is a TypeScript string literal union. Components switch on `error.type`.

**Rationale**: Different error types need different UI (countdown timer for 429, "try again" for 5xx, validation echo for 422). Stringly-typed errors force components to regex-match messages, which breaks when copy changes. Discriminated unions are TypeScript's idiomatic way to model variants and let the compiler enforce exhaustive handling.

**Rejected**: Multiple boolean flags (`isRateLimited`, `isTimeout`, …) — combinatorial explosion and contradictory states become representable.

### ADR-7: In-memory rate limiter for v1 (not Redis-backed)

**Decision**: slowapi's default in-memory storage backend. Redis-backed storage is documented as a future migration path but not implemented now.

**Rationale**: Single-instance backend deployment for the demo. In-memory is simpler, has no network dependency on the hot path, and the rate-limit accuracy across restarts is acceptable (worst case: attacker restarts process to reset their bucket, which requires controlling the host). When we scale to multiple instances, swap `storage_uri="redis://..."` and we already have Upstash configured.

**Rejected**: Redis-backed from day one — adds latency to every request (Upstash REST round-trip ~30-80ms) for a benefit only realized in a multi-instance topology we are not deploying yet.

### ADR-8: Cache key derivation — normalized question + corpus_version, no card_mentions in v1

**Decision**: `cache_key = sha256(question.strip().lower() + "|" + corpus_version)`. `card_mentions` is validated but **not** mixed into the cache key in v1.

**Rationale**: card_mentions in v1 is an additional input signal but does not change retrieval logic yet (planned for a later change). Mixing it into the key now would fragment the cache for no benefit. Question normalization (strip + lowercase) is intentional to coalesce trivial variations. corpus_version is essential so we never serve stale answers after re-ingestion.

**Rejected**: (a) Include card_mentions immediately — fragments cache without proportional hit-rate benefit until the retrieval actually uses them. (b) More aggressive normalization (remove punctuation, stemming) — risks merging semantically different queries; can be added once we measure false-merge rate.

## 6. Risks & Open Questions

- **In-memory rate limit**: resets on deploy. Acceptable for v1; revisit when traffic > 1 req/s sustained.
- **Cache stampede**: if 10 identical queries arrive simultaneously on a cold cache, all 10 hit Gemini. v1 accepts this; mitigation (single-flight lock) is a future change.
- **Langfuse cost at scale**: free tier covers demo volume. Monitor `langfuse_client.events_queued` if traffic grows.
- **structlog + Uvicorn access logs**: uvicorn's stdlib access log needs to be muted or piped through structlog. Decision: mute uvicorn access log, emit our own structured access log from a middleware that runs after slowapi.
- **Post-gen validation false positives**: regex-based citation guard may reject legitimate Gemini outputs. Mitigation: log over fail on borderline (sanitize answer to remove suspicious fragment, keep response), only outright reject when full prompt leak is detected.
- **Frontend timeout vs. server-side timeout**: client aborts at 10s, server Gemini timeout is 30s. Client may abort while server is still processing — wasted Gemini call. Accepted in v1; mitigated by cache (next identical query hits cache).

## 7. What This Design Does Not Change

- RAG retrieval algorithm (`hybrid_search`, RRF fusion, top_k) is untouched.
- Database schema is untouched.
- `Embedder` and Gemini client lifecycle in lifespan is untouched.
- Frontend page structure, Tailwind theming, and component composition are untouched.
- Existing exception handlers in `query.py` keep their status codes; new layers add 429 and 422 as additional codes.
