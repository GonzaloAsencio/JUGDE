import logging
import sys
from typing import Any

import structlog

langfuse_client: Any = None


def _before_send_filter(event: dict, hint: dict) -> dict | None:
    """Drop 4xx exceptions from Sentry — only unhandled / 5xx reach Sentry."""
    from fastapi import HTTPException

    exc_info = hint.get("exc_info")
    if exc_info:
        exc = exc_info[1]
        if isinstance(exc, HTTPException) and exc.status_code < 500:
            return None
    return event


def init_observability(settings: Any) -> None:
    """Initialise Sentry, Langfuse, and structlog.

    Each service is optional: if its env var is absent the feature is silently skipped.
    Called inside lifespan AFTER sentry_sdk.init at module top.
    """
    global langfuse_client

    _configure_structlog(settings.app_env)

    if settings.langfuse_secret_key and settings.langfuse_public_key:
        try:
            from langfuse import Langfuse  # type: ignore[import-untyped]

            langfuse_client = Langfuse(
                secret_key=settings.langfuse_secret_key,
                public_key=settings.langfuse_public_key,
                host=settings.langfuse_host,
            )
            logging.getLogger(__name__).info("Langfuse tracing enabled.")
        except Exception as e:
            logging.getLogger(__name__).warning("Langfuse init failed — tracing disabled: %s", e)
            langfuse_client = None


def _configure_structlog(app_env: str) -> None:
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if app_env == "production":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging through structlog's foreign_pre_chain
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )


def get_logger(name: str) -> Any:
    """Return a structlog bound logger for the given name."""
    return structlog.get_logger(name)


def observe_or_noop(fn: Any, name: str = "") -> Any:
    """Wrap *fn* with a Langfuse span if client is available; otherwise return *fn* unchanged."""
    if langfuse_client is None:
        return fn

    try:
        from langfuse.decorators import observe  # type: ignore[import-untyped]

        label = name or fn.__name__
        return observe(name=label)(fn)
    except Exception:
        return fn
