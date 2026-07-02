import psycopg2
from psycopg2.pool import PoolError
from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.observability import get_logger
from app.rag.generation import GenerationError, GenerationTimeout
from app.rag.pipeline import answer_question
from app.rag.provider import LLMProvider
from app.rag.schemas import QueryRequest, QueryResponse

logger = get_logger(__name__)

router = APIRouter()


def _query_limits() -> str:
    """Límite leído de settings en cada request (slowapi evalúa callables lazy)."""
    settings = get_settings()
    return f"{settings.rate_limit_per_min}/minute;{settings.rate_limit_per_day}/day"


def get_embedder(request: Request):
    return request.app.state.embedder


def get_db_pool(request: Request):
    return request.app.state.db_pool


def get_llm_provider(request: Request) -> LLMProvider:
    return request.app.state.llm_provider


@router.post("/query", response_model=QueryResponse)
@limiter.limit(_query_limits)
def query(
    body: QueryRequest,
    request: Request,
    embedder=Depends(get_embedder),
    pool=Depends(get_db_pool),
    provider: LLMProvider = Depends(get_llm_provider),
    settings=Depends(get_settings),
) -> QueryResponse:
    """POST /query — embed -> retrieve -> generate.

    Sync handler on purpose: the pipeline is fully blocking (embed, DB, LLM,
    cache), so FastAPI runs this in its threadpool and serves requests
    concurrently. An ``async`` handler would run the blocking work on the event
    loop and serialize the whole app to one request at a time.
    """
    if request.app.state.corpus_version is None:
        raise HTTPException(status_code=503, detail="Corpus not loaded. Run ingest pipeline first.")
    try:
        return answer_question(
            body.question, embedder, pool, provider, settings, body.card_mentions,
            corpus_version=request.app.state.corpus_version,
        )
    except GenerationTimeout as e:
        logger.warning("LLM timeout", error=str(e))
        raise HTTPException(status_code=504, detail="Generation timeout") from e
    except GenerationError as e:
        logger.error("LLM error", error=str(e))
        raise HTTPException(status_code=502, detail="Generation service error") from e
    except PoolError as e:
        # Every pooled connection is in use — shed load fast instead of piling
        # up. A short Retry-After nudges the client to back off and try again.
        logger.warning("DB pool exhausted", error=str(e))
        raise HTTPException(
            status_code=503,
            detail="Server busy, please retry shortly.",
            headers={"Retry-After": "2"},
        ) from e
    except psycopg2.OperationalError as e:
        # Log the exception TYPE, not str(e): psycopg2 operational errors can
        # embed the DSN (host/port/user) which would then leak into logs/Sentry.
        logger.error("DB unavailable", error_type=type(e).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable") from e
    except Exception as e:
        logger.error("Unexpected error in query handler", error_type=type(e).__name__)
        raise HTTPException(status_code=500, detail="Internal server error") from e
