from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


def _rate_limit_key(request: Request) -> str:
    """Return the client IP when rate limiting is enabled, or a constant key
    that never exhausts any limit when the flag is disabled."""
    from app.config import get_settings  # local import avoids circular deps at module load

    settings = get_settings()
    if not settings.rate_limit_enabled:
        return "__disabled__"
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    retry_after = getattr(exc, "retry_after", None) or 60
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."},
        headers={"Retry-After": str(retry_after)},
    )
