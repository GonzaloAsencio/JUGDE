"""GET /api/v1/usage — the user's own daily token meter (Fase 5, plan §5.4).

Works with the metering flag OFF on purpose: the flag only gates the 429 in
enforce_quota, while this endpoint just reports the counters — that is how a
dark flip is verified before enabling enforcement. What the user sees here is
their PERSONAL quota; the global budget deliberately never appears (it only
surfaces in the 429 detail when exhausted — advertising the shared pool's
remainder would hand abusers a drain gauge).
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
    }
