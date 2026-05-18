import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.observability import get_logger
from app.rag.generation import GenerationError, GenerationTimeout
from app.rag.pipeline import answer_question
from app.rag.schemas import QueryRequest, QueryResponse

logger = get_logger(__name__)

router = APIRouter()


def get_embedder(request: Request):
    return request.app.state.embedder


def get_db_pool(request: Request):
    return request.app.state.db_pool


def get_llm_client(request: Request):
    return request.app.state.llm_client


@router.post("/query", response_model=QueryResponse)
@limiter.limit("10/minute;100/day")
async def query(
    body: QueryRequest,
    request: Request,
    embedder=Depends(get_embedder),
    pool=Depends(get_db_pool),
    llm_client=Depends(get_llm_client),
    settings=Depends(get_settings),
) -> QueryResponse:
    """POST /query — embed -> retrieve -> generate."""
    if request.app.state.corpus_version is None:
        raise HTTPException(status_code=503, detail="Corpus not loaded. Run ingest pipeline first.")
    try:
        return await answer_question(body.question, embedder, pool, llm_client, settings, body.card_mentions)
    except GenerationTimeout as e:
        logger.warning("LLM timeout", error=str(e))
        raise HTTPException(status_code=504, detail="Generation timeout") from e
    except GenerationError as e:
        logger.error("LLM error", error=str(e))
        raise HTTPException(status_code=502, detail="Generation service error") from e
    except psycopg2.OperationalError as e:
        logger.error("DB unavailable", error=str(e))
        raise HTTPException(status_code=503, detail="Database unavailable") from e
    except Exception as e:
        logger.error("Unexpected error in query handler", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error") from e
