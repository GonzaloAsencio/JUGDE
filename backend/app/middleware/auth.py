import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Shallow /health stays public — HF Spaces uses it as container healthcheck.
_EXEMPT_PATHS = frozenset({"/health"})

_HEADER_NAME = "X-Proxy-Secret"


class ProxySecretMiddleware(BaseHTTPMiddleware):
    """Reject requests that don't carry the shared secret set by the Next proxy.

    Disabled when settings.proxy_shared_secret is None (local dev). The 401
    detail is deliberately generic so the mechanism is not advertised.
    """

    async def dispatch(self, request: Request, call_next):
        settings = getattr(request.app.state, "settings", None)
        expected = getattr(settings, "proxy_shared_secret", None)

        if not expected or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        provided = request.headers.get(_HEADER_NAME, "")
        if not secrets.compare_digest(provided.encode(), expected.encode()):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        return await call_next(request)
