import json

import psycopg2
from psycopg2.pool import PoolError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.db import resolve_corpus_version
from app.middleware.rate_limit import limiter
from app.observability import get_logger
from app.rag.generation import GenerationError, GenerationTimeout
from app.rag.pipeline import answer_question, answer_question_stream
from app.rag.provider import LLMProvider
from app.rag.schemas import QueryRequest, QueryResponse
from app.usage import Identity, enforce_quota, record_query_usage

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


def get_hard_provider(request: Request) -> LLMProvider | None:
    # None unless hard-query routing is enabled at startup (see main.py).
    return getattr(request.app.state, "hard_provider", None)


def _resolve_corpus_or_503(request: Request, pool, settings) -> str:
    """Resolve corpus_version (re-resolving once after an empty-corpus startup),
    or raise 503 — shared by /query and /query/stream."""
    corpus_version = request.app.state.corpus_version
    if corpus_version is None:
        # Startup found an empty corpus. An ingest may have populated it since —
        # re-resolve once (and cache it) instead of forcing a restart.
        corpus_version = resolve_corpus_version(pool, settings)
        request.app.state.corpus_version = corpus_version
    if corpus_version is None:
        raise HTTPException(status_code=503, detail="Corpus not loaded. Run ingest pipeline first.")
    return corpus_version


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/query/stream")
@limiter.limit(_query_limits)
def query_stream(
    body: QueryRequest,
    request: Request,
    # Quota gate BEFORE the stream starts: over-quota must be a clean 429
    # status, never an in-band error event (plan §5.3). The dependency also
    # resolves the identity used for post-response bookkeeping below.
    identity: Identity = Depends(enforce_quota),
    embedder=Depends(get_embedder),
    pool=Depends(get_db_pool),
    provider: LLMProvider = Depends(get_llm_provider),
    hard_provider: LLMProvider | None = Depends(get_hard_provider),
    settings=Depends(get_settings),
) -> StreamingResponse:
    """POST /query/stream — /query with SSE delivery (2.5).

    Sync handler + sync generator on purpose (see /query): FastAPI iterates the
    generator in its threadpool, so the blocking pipeline streams without
    tying up the event loop.

    Events: ``token`` (text delta), ``restart`` (client clears the partial
    bubble), ``final`` (the canonical QueryResponse — always last on success),
    ``error`` (terminal; mid-stream failures cannot change the HTTP status, so
    the /query error mapping is delivered in-band instead).
    """
    corpus_version = _resolve_corpus_or_503(request, pool, settings)

    def event_source():
        try:
            for kind, payload in answer_question_stream(
                body.question, embedder, pool, provider, settings, body.card_mentions,
                corpus_version=corpus_version, hard_provider=hard_provider,
            ):
                if kind == "token":
                    yield _sse("token", {"text": payload})
                elif kind == "restart":
                    yield _sse("restart", {})
                else:
                    # Book the spend when the final response exists, BEFORE
                    # yielding it: a client that disconnects right after the
                    # last token must not produce an unmetered query.
                    record_query_usage(pool, identity, payload)
                    yield _sse("final", payload.model_dump())
        except GenerationTimeout as e:
            logger.warning("LLM timeout", error=str(e))
            yield _sse("error", {"detail": "Generation timeout"})
        except GenerationError as e:
            logger.error("LLM error", error=str(e))
            yield _sse("error", {"detail": "Generation service error"})
        except PoolError as e:
            logger.warning("DB pool exhausted", error=str(e))
            yield _sse("error", {"detail": "Server busy, please retry shortly."})
        except psycopg2.OperationalError as e:
            # Log the exception TYPE, not str(e) — see the /query handler.
            logger.error("DB unavailable", error_type=type(e).__name__)
            yield _sse("error", {"detail": "Database unavailable"})
        except Exception as e:
            logger.error("Unexpected error in query stream handler", error_type=type(e).__name__)
            yield _sse("error", {"detail": "Internal server error"})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        # no-cache for proxies; X-Accel-Buffering opts out of buffering in
        # nginx-style reverse proxies (the HF Space sits behind one) — a
        # buffered SSE stream degrades to one big flush, i.e. no streaming.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/query", response_model=QueryResponse)
@limiter.limit(_query_limits)
def query(
    body: QueryRequest,
    request: Request,
    # See query_stream: gate + identity resolution in one dependency.
    identity: Identity = Depends(enforce_quota),
    embedder=Depends(get_embedder),
    pool=Depends(get_db_pool),
    provider: LLMProvider = Depends(get_llm_provider),
    hard_provider: LLMProvider | None = Depends(get_hard_provider),
    settings=Depends(get_settings),
) -> QueryResponse:
    """POST /query — embed -> retrieve -> generate.

    Sync handler on purpose: the pipeline is fully blocking (embed, DB, LLM,
    cache), so FastAPI runs this in its threadpool and serves requests
    concurrently. An ``async`` handler would run the blocking work on the event
    loop and serialize the whole app to one request at a time.
    """
    corpus_version = _resolve_corpus_or_503(request, pool, settings)
    try:
        response = answer_question(
            body.question, embedder, pool, provider, settings, body.card_mentions,
            corpus_version=corpus_version, hard_provider=hard_provider,
        )
        # Post-response bookkeeping (Redis counters + ledger) lives HERE, not
        # in the pipeline — the pipeline never learns identity. Best-effort:
        # record_query_usage swallows every infrastructure failure.
        record_query_usage(pool, identity, response)
        return response
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
