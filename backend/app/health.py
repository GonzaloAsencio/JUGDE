import importlib.metadata
from datetime import datetime, timezone

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])

try:
    _VERSION = importlib.metadata.version("app")
except Exception:
    _VERSION = "0.1.0"


@router.api_route("/health", methods=["GET", "HEAD"])
def health_shallow(request: Request) -> dict:
    """Shallow health check — no I/O, responds in <50ms."""
    corpus_version = getattr(request.app.state, "corpus_version", None)
    return {
        "status": "ok",
        "version": _VERSION,
        "corpus_version": corpus_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/deep")
async def health_deep(request: Request) -> dict:
    """Deep health check — probes DB, Redis, and Gemini.

    Always returns HTTP 200; sets status='degraded' on partial failure.
    """
    checks: dict[str, bool] = {}

    # DB probe
    try:
        pool = request.app.state.db_pool
        from app.db import get_conn

        with get_conn(pool) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        checks["db"] = True
    except Exception:
        checks["db"] = False

    # Redis probe
    try:
        from app.cache import _redis_client

        if _redis_client is not None:
            _redis_client.ping()
            checks["redis"] = True
        else:
            checks["redis"] = False
    except Exception:
        checks["redis"] = False

    # LLM liveness probe — delegated to provider
    try:
        provider = request.app.state.llm_provider
        error = provider.health_check()
        checks["llm"] = error is None
    except Exception:
        checks["llm"] = False

    overall = "ok" if all(checks.values()) else "degraded"
    return {"status": overall, "checks": checks}
