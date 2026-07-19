"""Per-user daily token metering (Fase 5): identity, quotas, recording, ledger.

Design rules (plan §5.1–5.3):

- FAIL-OPEN everywhere. Metering exists to protect the free tier, not to take
  the product down: any Redis or DB failure logs a warning and the query
  passes. slowapi's per-IP limits remain as the backstop during an outage.
- Identity mirrors the rate_limit trust model (see
  rate_limit._rate_limit_key): the proxy mints identity headers and proves
  itself with X-Proxy-Secret; the backend never validates cookies or JWTs.
  A header without that proof must never mint a fresh quota bucket.
- Two ceilings per request: the PERSONAL daily quota (tier decides it) and
  the GLOBAL daily budget — the latter is what actually protects the
  provider. The check-then-act race is accepted: quotas are soft, overshoot
  is bounded by one in-flight request per racer.
- The counters live in Redis via the cache's client (see cache.get_redis) as
  ``tokens:{user_id}:{YYYYMMDD}`` / ``tokens:global:{YYYYMMDD}`` with a TTL
  to midnight UTC plus a margin, so keys clean themselves up.
"""
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from slowapi.util import get_remote_address

from app.cache import get_redis
from app.observability import get_logger

logger = get_logger(__name__)

# Anything longer is not one of our IDs (anon:{uuid} ~41 chars, auth:{sub}
# tops out well below this) — reject instead of storing attacker-sized keys.
_MAX_USER_ID_LEN = 128

# Counters outlive their day by this much so a request straddling midnight
# still EXPIREs cleanly; the day key rotates anyway, so the stale key is
# never read again.
_EXPIRE_MARGIN_S = 3600


@dataclass(frozen=True)
class Identity:
    user_id: str  # "anon:{uuid}" | "auth:{sub}" | "ip:{addr}"
    tier: str  # "anon" | "auth"


@dataclass(frozen=True)
class QuotaStatus:
    allowed: bool
    reason: str | None  # None | "personal" | "global"
    used: int
    quota: int
    resets_at: str  # ISO timestamp of the next midnight UTC


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _day(now: datetime) -> str:
    return now.strftime("%Y%m%d")


def _next_midnight(now: datetime) -> datetime:
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def seconds_to_reset(now: datetime | None = None) -> int:
    now = now or _utc_now()
    return max(int((_next_midnight(now) - now).total_seconds()), 1)


def user_key(user_id: str, now: datetime) -> str:
    return f"tokens:{user_id}:{_day(now)}"


def global_key(now: datetime) -> str:
    return f"tokens:global:{_day(now)}"


def _request_settings(request: Request):
    """Settings resolved in lifespan (app.state) or the global ones — same
    pattern as rate_limit, for the same import-order reason."""
    from app.config import get_settings

    return getattr(request.app.state, "settings", None) or get_settings()


def get_user_identity(request: Request) -> Identity:
    """Resolve who is asking, per the trusted-proxy contract.

    ``X-User-Id`` (``anon:{uuid}`` | ``auth:{sub}`` — the prefix decides the
    tier) is honored ONLY when the request carries a valid ``X-Proxy-Secret``:
    the proxy mints the anonymous cookie and validates the Supabase session,
    so the header is its word, not the client's. Behind the same proof,
    ``X-Real-IP`` identifies proxied requests without a cookie. Without proof,
    the remote address — a spoofed header never grants a fresh bucket
    (same decision as rate_limit._rate_limit_key for X-Real-IP).
    """
    settings = _request_settings(request)
    secret = settings.proxy_shared_secret
    if secret:
        provided = request.headers.get("X-Proxy-Secret", "")
        if secrets.compare_digest(provided.encode(), secret.encode()):
            uid = request.headers.get("X-User-Id", "").strip()
            if len(uid) <= _MAX_USER_ID_LEN:
                if uid.startswith("auth:") and len(uid) > len("auth:"):
                    return Identity(user_id=uid, tier="auth")
                if uid.startswith("anon:") and len(uid) > len("anon:"):
                    return Identity(user_id=uid, tier="anon")
            real_ip = request.headers.get("X-Real-IP", "").strip()
            if real_ip:
                return Identity(user_id=f"ip:{real_ip}", tier="anon")
    return Identity(user_id=f"ip:{get_remote_address(request)}", tier="anon")


def personal_quota(settings, tier: str) -> int:
    return settings.auth_daily_token_quota if tier == "auth" else settings.anon_daily_token_quota


def check_quota(identity: Identity, settings) -> QuotaStatus:
    """Read both ceilings for *identity*. Fail-open: no Redis, or a Redis
    error, reports allowed with used=0 — never blocks on infrastructure."""
    now = _utc_now()
    quota = personal_quota(settings, identity.tier)
    resets_at = _next_midnight(now).isoformat()
    redis = get_redis()
    if redis is None:
        return QuotaStatus(True, None, 0, quota, resets_at)
    try:
        used = int(redis.get(user_key(identity.user_id, now)) or 0)
        global_used = int(redis.get(global_key(now)) or 0)
    except Exception as e:
        logger.warning("metering.check_failed — fail-open", error=str(e))
        return QuotaStatus(True, None, 0, quota, resets_at)
    if used >= quota:
        return QuotaStatus(False, "personal", used, quota, resets_at)
    if global_used >= settings.global_daily_token_budget:
        return QuotaStatus(False, "global", used, quota, resets_at)
    return QuotaStatus(True, None, used, quota, resets_at)


def record_usage(identity: Identity, total_tokens: int) -> None:
    """Two INCRBY (personal + global day counters) + EXPIRE each. Best-effort:
    a Redis failure means this spend goes uncounted — logged, never raised."""
    if total_tokens <= 0:
        return
    redis = get_redis()
    if redis is None:
        return
    now = _utc_now()
    ttl = seconds_to_reset(now) + _EXPIRE_MARGIN_S
    try:
        for key in (user_key(identity.user_id, now), global_key(now)):
            redis.incrby(key, total_tokens)
            # EXPIRE on every write refreshes an unlikely-stale TTL and is one
            # extra cheap command; NX-style semantics aren't needed because the
            # deadline (midnight + margin) is the same all day.
            redis.expire(key, ttl)
    except Exception as e:
        logger.warning("metering.record_failed — usage not counted", error=str(e))


def enforce_quota(request: Request) -> Identity:
    """FastAPI dependency for /query and /query/stream (a dependency, not
    middleware — plan §5.3): resolves identity, and 429s over-quota requests
    BEFORE the pipeline runs (a stream must fail with a clean status, not an
    in-band error event). The flag only gates the 429 — identity always
    resolves so the endpoints can keep recording usage while dark.
    """
    identity = get_user_identity(request)
    settings = _request_settings(request)
    if not settings.metering_enabled:
        return identity
    status = check_quota(identity, settings)
    if status.allowed:
        return identity

    retry_after = seconds_to_reset()
    if status.reason == "personal":
        # Distinguishable by cause (plan §5.3): the anon message is the
        # login funnel; the auth one just states the reset.
        detail = (
            "Daily token limit reached — sign in to raise your limit. Resets at midnight UTC."
            if identity.tier == "anon"
            else "Daily token limit reached. Resets at midnight UTC."
        )
    else:
        detail = "The demo exhausted today's shared token budget. Resets at midnight UTC."
    logger.info(
        "metering.quota_exceeded",
        tier=identity.tier,
        reason=status.reason,
        used=status.used,
        quota=status.quota,
    )
    raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(retry_after)})


_LEDGER_INSERT = """
INSERT INTO usage_ledger
    (user_id, model, prompt_tokens, output_tokens, total_tokens, estimated, cached)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


def record_ledger(pool, identity: Identity, response) -> None:
    """Append the audit row for a served response. Zero PII: the opaque
    user_id and token counts only — never the question (plan §5.1).
    Best-effort post-response: a ledger failure never fails a query."""
    usage = getattr(response, "usage", None)
    try:
        from app.db import get_conn

        with get_conn(pool) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _LEDGER_INSERT,
                    (
                        identity.user_id,
                        getattr(usage, "llm_model", None),
                        getattr(usage, "prompt_tokens", 0) if usage else 0,
                        getattr(usage, "output_tokens", 0) if usage else 0,
                        getattr(usage, "total_tokens", 0) if usage else 0,
                        bool(getattr(usage, "estimated", False)) if usage else False,
                        bool(getattr(response, "cache_hit", False)),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.warning("metering.ledger_failed", error=str(e))


def record_query_usage(pool, identity: Identity, response) -> None:
    """Post-response bookkeeping shared by /query and /query/stream: Redis
    counters (skipped for cache hits — usage is None, nothing was spent) and
    the ledger row (always — cached=true rows are the cache-savings metric).
    Runs with the flag OFF too: dark counters are how the flip is verified."""
    usage = getattr(response, "usage", None)
    if usage is not None:
        record_usage(identity, usage.total_tokens)
    record_ledger(pool, identity, response)
