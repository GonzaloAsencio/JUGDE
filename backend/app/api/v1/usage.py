"""GET /api/v1/usage — the user's own daily token meter (Fase 5, plan §5.4).

Works with the metering flag OFF on purpose: the flag only gates the 429 in
enforce_quota, while this endpoint just reports the counters — that is how a
dark flip is verified before enabling enforcement. What the user sees here is
their PERSONAL quota; the global budget's REMAINDER deliberately never appears
(advertising the shared pool's remainder would hand abusers a drain gauge).
``available`` is the sole exception: a boolean saying whether the caller can
query right now. It leaks no gauge — a blocked caller already learns this from
the 429 — and it lets the badge stay honest instead of showing "20K left" while
the shared budget is spent (the personal remainder alone is misleading then).
"""
from fastapi import APIRouter, Request

from app.middleware.rate_limit import limiter
from app.usage import _request_settings, check_quota, get_user_identity

router = APIRouter()


@router.get("/usage")
# Own soft limit: the frontend refreshes the badge after every answer, so this
# is chattier than /query — but it must never eat the /query buckets.
@limiter.limit("30/minute")
def usage(request: Request) -> dict:
    identity = get_user_identity(request)
    settings = _request_settings(request)
    status = check_quota(identity, settings)
    return {
        "used": status.used,
        "quota": status.quota,
        "remaining": max(status.quota - status.used, 0),
        "resets_at": status.resets_at,
        "tier": identity.tier,
        # True when the caller may query now. False if EITHER ceiling is spent
        # (personal or the shared global) — the badge needs this because the
        # personal remainder can be full while the global pool blocks everyone.
        "available": status.allowed,
    }
