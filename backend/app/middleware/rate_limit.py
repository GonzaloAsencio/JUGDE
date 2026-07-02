import os
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


def _request_settings(request: Request):
    """Settings resueltas en lifespan (app.state) o, si aún no hay, las globales."""
    from app.config import get_settings  # local import avoids circular deps at module load

    return getattr(request.app.state, "settings", None) or get_settings()


def _rate_limit_key(request: Request) -> str:
    """Return the per-user key for rate limiting.

    Trusted-proxy mode: when proxy_shared_secret is configured AND the request
    carries the valid X-Proxy-Secret, the X-Real-IP header (set by the Next
    proxy) identifies the real user. Without that proof the header is ignored
    — a spoofed X-Real-IP must never grant a fresh bucket.
    """
    settings = _request_settings(request)
    if not settings.rate_limit_enabled:
        return "__disabled__"

    secret = settings.proxy_shared_secret
    if secret:
        provided = request.headers.get("X-Proxy-Secret", "")
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip and secrets.compare_digest(provided.encode(), secret.encode()):
            return real_ip

    return get_remote_address(request)


def _resolve_storage_uri() -> str:
    """Backing store for the rate-limit counters.

    Defaults to in-memory (per-process). That is correct for a single worker but
    USELESS across replicas: each process keeps its own counters, so the real
    limit becomes N × the configured value and resets on restart. Set
    RATE_LIMIT_STORAGE_URI to a shared ``redis://`` when running more than one
    worker/replica. Note: this is a native Redis URI (Upstash exposes a
    ``rediss://`` endpoint), NOT the Upstash REST URL used by the response cache.

    Read from the environment rather than Settings because the limiter is built
    at import time, before the app's Settings are resolved in the lifespan.
    """
    return os.getenv("RATE_LIMIT_STORAGE_URI", "").strip() or "memory://"


limiter = Limiter(key_func=_rate_limit_key, storage_uri=_resolve_storage_uri())


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    retry_after = getattr(exc, "retry_after", None) or 60
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."},
        headers={"Retry-After": str(retry_after)},
    )
