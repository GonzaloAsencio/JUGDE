import logging

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.rag.generation import GenerationError, GenerationTimeout
from app.rag.pipeline import answer_question
from app.rag.schemas import QueryRequest, QueryResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def get_embedder(request: Request):
    return request.app.state.embedder


def get_db_pool(request: Request):
    return request.app.state.db_pool


def get_gemini_client(request: Request):
    return request.app.state.gemini_client


@router.post("/query", response_model=QueryResponse)
@limiter.limit("10/minute;100/day")
def query(
    body: QueryRequest,
    request: Request,
    embedder=Depends(get_embedder),
    pool=Depends(get_db_pool),
    gemini=Depends(get_gemini_client),
    settings=Depends(get_settings),
) -> QueryResponse:
    """POST /query — embed → retrieve → generate."""
    if request.app.state.corpus_version is None:
        raise HTTPException(status_code=503, detail="Corpus not loaded. Run ingest pipeline first.")
    try:
        return answer_question(body.question, embedder, pool, gemini, settings)
    except GenerationTimeout as e:
        logger.warning("Gemini timeout: %s", e)
        raise HTTPException(status_code=504, detail="Generation timeout") from e
    except GenerationError as e:
        logger.error("Gemini error: %s", e)
        raise HTTPException(status_code=502, detail="Generation service error") from e
    except psycopg2.OperationalError as e:
        logger.error("DB unavailable: %s", e)
        raise HTTPException(status_code=503, detail="Database unavailable") from e
    except Exception as e:
        logger.exception("Unexpected error in query handler")
        raise HTTPException(status_code=500, detail="Internal server error") from e
