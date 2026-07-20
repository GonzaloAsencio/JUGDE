import importlib.metadata
from datetime import datetime, timezone

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])

try:
    _VERSION = importlib.metadata.version("app")
except Exception:
    _VERSION = "0.1.0"


def _model_of(provider) -> str | None:
    """The model a provider on app.state actually calls, or None when absent.

    hard_provider is legitimately None (routing flag off), and app.state may not
    carry a provider at all during a degraded startup — both report None rather
    than raising, because /health must answer even when the app is unhealthy.
    """
    return getattr(provider, "model", None) if provider is not None else None


@router.api_route("/health", methods=["GET", "HEAD"])
def health_shallow(request: Request) -> dict:
    """Shallow health check — no I/O, responds in <50ms.

    Reports the RUNNING models: on 2026-07-17 "which model does prod answer
    with?" had no answer anywhere — this endpoint carried version and
    corpus_version, /health/deep carried booleans, and the logs named the model
    from settings instead of the provider, so they lied whenever the
    openai_compat knobs were left set under llm_provider='gemini'. An operator
    swapping providers by rate limit could not tell which one was live. The
    provider objects are already on app.state, so reading their model costs no
    I/O and keeps this shallow.
    """
    corpus_version = getattr(request.app.state, "corpus_version", None)
    provider = getattr(request.app.state, "llm_provider", None)
    settings = getattr(request.app.state, "settings", None)
    return {
        "status": "ok",
        "version": _VERSION,
        "corpus_version": corpus_version,
        "models": {
            "main": _model_of(provider),
            # None is the honest answer when routing is off, not an omitted key:
            # a missing field reads as "unknown", and "no hard model" is a fact.
            "hard": _model_of(getattr(request.app.state, "hard_provider", None)),
        },
        # The 2.1/2.2 flips are env vars whose failure mode is SILENT (a typo'd
        # HYDE_MODEL degrades to raw-only retrieval at call time, a missing
        # SKIP_HYDE_WHEN_ROUTED just spends the call) — so the flip must be
        # verifiable from outside. hyde model comes from the provider object
        # (the authority on what it calls, same rule as models above); the skip
        # flag is pipeline config, so Settings IS its authority.
        "hyde": {
            "model": getattr(provider, "hyde_model", None) if provider is not None else None,
            "skip_when_routed": getattr(settings, "skip_hyde_when_routed", None),
        },
        # Same rule as the hyde flags (#78): a flip whose failure mode is
        # silent must be verifiable from outside. The metering flag's two-step
        # deploy checks this field before and after setting the env.
        "metering": {
            "enabled": getattr(settings, "metering_enabled", None),
        },
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
