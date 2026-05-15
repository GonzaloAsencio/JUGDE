import importlib.metadata
from datetime import datetime, timezone

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])

try:
    _VERSION = importlib.metadata.version("app")
except Exception:
    _VERSION = "0.1.0"


@router.get("/health")
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

    # Gemini liveness probe
    try:
        import google.generativeai as genai

        gemini = request.app.state.gemini_client
        gemini.generate_content(
            "ping",
            generation_config=genai.types.GenerationConfig(max_output_tokens=1),
        )
        checks["llm"] = True
    except Exception as e:
        # 429 means the key is valid — not a real failure
        if "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower():
            checks["llm"] = True
        else:
            checks["llm"] = False

    overall = "ok" if all(checks.values()) else "degraded"
    return {"status": overall, "checks": checks}
