from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.query import router as query_router
from app.cache import close_redis, init_redis
from app.config import get_settings
from app.db import close_pool, init_pool, resolve_corpus_version
from app.health import router as health_router
from app.middleware.auth import ProxySecretMiddleware
from app.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from app.observability import get_logger, init_observability
from google import genai

from app.rag.embedder import Embedder
from app.rag.provider import create_hard_provider, create_provider

_settings = get_settings()

if _settings.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    sentry_sdk.init(
        dsn=_settings.sentry_dsn,
        integrations=[FastApiIntegration()],
        traces_sample_rate=0.0,
        sample_rate=_settings.sentry_sample_rate,
        before_send=lambda event, hint: __import__(
            "app.observability", fromlist=["_before_send_filter"]
        )._before_send_filter(event, hint),
    )

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Load settings
    settings = get_settings()
    init_observability(settings)
    logger.info("Settings loaded.")

    # 2. Init DB pool
    pool = init_pool(settings.database_url, minconn=settings.db_pool_min, maxconn=settings.db_pool_max)
    logger.info("DB pool initialized.")

    # 3. Resolve corpus_version. If the corpus is empty at startup we don't fail:
    #    the query endpoint re-resolves on demand, so an ingest run afterwards is
    #    picked up without a restart.
    corpus_version = resolve_corpus_version(pool, settings)
    if corpus_version is None:
        logger.warning("corpus_chunks is empty -- queries 503 until ingest runs, then re-resolve on demand.")
    else:
        logger.info("corpus_version resolved", corpus_version=corpus_version)

    # 4. Load embedder (~5-10s intentional)
    logger.info("Loading embedder (this takes ~5-10s)...")
    embedder = Embedder.load(settings.model_name)
    logger.info("Embedder loaded.")

    # 5. Init LLM client
    if settings.llm_provider == "gemini":
        from google.genai import types as genai_types
        llm_client = genai.Client(api_key=settings.gemini_api_key)
        logger.info("Gemini client initialized.")

        # 6. Ping Gemini to validate API key (rate limit errors are warnings, not fatal)
        try:
            llm_client.models.generate_content(
                model=settings.gemini_model,
                contents="ping",
                config=genai_types.GenerateContentConfig(max_output_tokens=5),
            )
            logger.info("Gemini ping successful.")
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower():
                logger.warning("Gemini ping hit rate limit (429) -- API key is valid, continuing.")
            else:
                close_pool(pool)
                raise RuntimeError(
                    f"Gemini ping failed -- invalid API key or unreachable: {e}"
                ) from e
    else:
        llm_client = None
        logger.info("LLM provider: openai_compat — skipping Gemini init.", base_url=settings.llm_base_url, model=settings.llm_model)

    # 7. Init Redis cache (optional -- skipped if env vars absent)
    if settings.upstash_redis_url and settings.upstash_redis_token:
        init_redis(settings.upstash_redis_url, settings.upstash_redis_token)
    else:
        # Loud on purpose: with the client unset, get/set_cached no-op silently,
        # so a missing env var looks identical to a cache bug from the outside.
        logger.warning("Cache disabled — UPSTASH_REDIS_URL/UPSTASH_REDIS_TOKEN not set.")

    # 8-9. Store everything on app.state
    app.state.embedder = embedder
    app.state.db_pool = pool
    app.state.llm_provider = create_provider(settings, llm_client)
    # Say out loud which model actually answers, and which configured knobs are
    # inert. Swapping providers by rate limit means llm_provider can lag behind
    # llm_model, and the lag is silent: create_provider ignores llm_model under
    # gemini. On 2026-07-17 that made a gate measure gemini-flash-lite while
    # every log line named gpt-oss-120b. Not fatal (keeping both sides
    # configured is how you flip in one edit) — but never again unsaid.
    logger.info(
        "Main LLM provider ready.",
        provider=settings.llm_provider,
        model=app.state.llm_provider.model,
    )
    stray = settings.stray_openai_compat_fields()
    if stray:
        logger.warning(
            "Ignoring openai_compat settings under the current provider — these do NOTHING "
            "until llm_provider=openai_compat.",
            llm_provider=settings.llm_provider,
            ignored=stray,
            answering_with=app.state.llm_provider.model,
        )
    # 4.2+4.3 hard-query routing: a second, Gemini-only provider on the
    # thinking model. Independent of the MAIN provider (prod runs Groq/
    # openai_compat as main) — create_hard_provider builds its own Gemini
    # client from gemini_api_key when needed. None (flag off) keeps the
    # pipeline byte-identical to pre-routing behaviour.
    app.state.hard_provider = create_hard_provider(settings, llm_client)
    if app.state.hard_provider is not None:
        logger.info("Hard-query routing enabled.", hard_model=settings.hard_gemini_model)
    app.state.corpus_version = corpus_version
    app.state.settings = settings

    # The resolved corpus_version reaches the pipeline through app.state (the
    # endpoint passes it into answer_question). We deliberately do NOT mutate the
    # lru_cache'd Settings singleton here — that shared, cached object would leak
    # the mutation into every get_settings() consumer and across tests.

    logger.info("Startup complete.", corpus_version=corpus_version)

    yield

    # 10. Teardown
    close_redis()
    close_pool(app.state.db_pool)
    logger.info("DB pool closed.")


app = FastAPI(title="Riftbound Judge AI", version="0.1.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
# Added after SlowAPIMiddleware so auth runs FIRST (Starlette: last added, first run)
# — unauthenticated requests must not consume rate-limit buckets.
app.add_middleware(ProxySecretMiddleware)
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

app.include_router(query_router, prefix="/api/v1")
app.include_router(health_router)
