import logging
from contextlib import asynccontextmanager

import google.generativeai as genai
from fastapi import FastAPI

from app.api.v1.query import router as query_router
from app.config import get_settings
from app.db import close_pool, get_conn, init_pool
from app.rag.embedder import Embedder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Load settings
    settings = get_settings()
    logger.info("Settings loaded.")

    # 2. Init DB pool
    pool = init_pool(settings.database_url, minconn=1, maxconn=5)
    logger.info("DB pool initialized.")

    # 3. Resolve corpus_version
    if settings.corpus_version and settings.corpus_version != "latest":
        corpus_version = settings.corpus_version
        logger.info("Using corpus_version from env: %s", corpus_version)
    else:
        with get_conn(pool) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(corpus_version) FROM corpus_chunks")
                row = cur.fetchone()
                if row is None or row[0] is None:
                    close_pool(pool)
                    raise RuntimeError(
                        "No corpus loaded: corpus_chunks table is empty. "
                        "Run the ingest pipeline first."
                    )
                corpus_version = row[0]
        logger.info("Resolved corpus_version from DB: %s", corpus_version)

    # 4. Load embedder (~5-10s intentional)
    logger.info("Loading embedder (this takes ~5-10s)...")
    embedder = Embedder.load(settings.model_name)
    logger.info("Embedder loaded.")

    # 5. Init Gemini client
    genai.configure(api_key=settings.gemini_api_key)
    gemini_client = genai.GenerativeModel(settings.gemini_model)
    logger.info("Gemini client initialized.")

    # 6. Ping Gemini to validate API key (rate limit errors are warnings, not fatal)
    try:
        gemini_client.generate_content(
            "ping",
            generation_config=genai.types.GenerationConfig(max_output_tokens=5),
        )
        logger.info("Gemini ping successful.")
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower():
            logger.warning("Gemini ping hit rate limit (429) — API key is valid, continuing.")
        else:
            close_pool(pool)
            raise RuntimeError(
                f"Gemini ping failed — invalid API key or unreachable: {e}"
            ) from e

    # 7-8. Store everything on app.state
    app.state.embedder = embedder
    app.state.db_pool = pool
    app.state.gemini_client = gemini_client
    app.state.corpus_version = corpus_version
    app.state.settings = settings

    # Patch settings so pipeline uses the resolved corpus_version
    settings.corpus_version = corpus_version

    logger.info("Startup complete. corpus_version=%s", corpus_version)

    yield

    # 9. Teardown
    close_pool(app.state.db_pool)
    logger.info("DB pool closed.")


app = FastAPI(title="Riftbound Judge AI", version="0.1.0", lifespan=lifespan)

app.include_router(query_router, prefix="/api/v1")
