from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.query import router as query_router
from app.cache import close_redis, init_redis
from app.config import get_settings
from app.db import close_pool, get_conn, init_pool
from app.health import router as health_router
from app.middleware.auth import ProxySecretMiddleware
from app.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from app.observability import get_logger, init_observability
from google import genai

from app.rag.embedder import Embedder
from app.rag.provider import create_provider

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

    # 3. Resolve corpus_version
    if settings.corpus_version and settings.corpus_version != "latest":
        corpus_version = settings.corpus_version
        logger.info("corpus_version from env", corpus_version=corpus_version)
    else:
        with get_conn(pool) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(corpus_version) FROM corpus_chunks")
                row = cur.fetchone()
                if row is None or row[0] is None:
                    logger.warning("corpus_chunks is empty -- queries will return 503 until ingest runs.")
                    corpus_version = None
                else:
                    corpus_version = row[0]
        logger.info("corpus_version resolved from DB", corpus_version=corpus_version)

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

    # 8-9. Store everything on app.state
    app.state.embedder = embedder
    app.state.db_pool = pool
    app.state.llm_provider = create_provider(settings, llm_client)
    app.state.corpus_version = corpus_version
    app.state.settings = settings

    # Patch settings so pipeline uses the resolved corpus_version
    settings.corpus_version = corpus_version

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
