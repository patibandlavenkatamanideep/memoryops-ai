"""Liveness + readiness probes."""

from __future__ import annotations

import time

from fastapi import APIRouter

from .. import __version__
from ..core.config import get_settings
from ..db.factory import get_repository

router = APIRouter(tags=["ops"])

# Captured at import so /healthz can report process uptime.
_PROCESS_START = time.monotonic()


@router.get("/healthz")
def healthz() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "uptime_seconds": round(time.monotonic() - _PROCESS_START, 1),
        "metrics_enabled": settings.metrics_enabled,
    }


@router.get("/healthz/workers")
def workers_health() -> dict:
    """Worker runtime health (v0.8): recent run history, dead-letter + failure
    counts, and the last run per scope. Content-free operational evidence."""
    from ..db.entities import OperationalAccessUnavailable
    from ..workers.orchestrator import summarize_runtime_health

    settings = get_settings()
    try:
        summary = summarize_runtime_health(
            get_repository(), limit=settings.worker_run_history_limit
        )
        healthy = summary["dead_letter_count"] == 0 and summary["failed_count"] == 0
        return {"healthy": healthy, **summary}
    except OperationalAccessUnavailable:
        # Not an error — global worker health needs a separately authorized
        # operational connection. Report it as an actionable, non-fatal state.
        return {
            "healthy": None,
            "detail": "operational access not configured",
            "hint": "set OPERATIONAL_DATABASE_URL to a monitoring role",
        }
    except Exception as exc:  # noqa: BLE001 — health must not raise
        return {"healthy": False, "detail": f"unavailable: {type(exc).__name__}"}


@router.get("/readyz")
def readyz() -> dict:
    settings = get_settings()
    ready = True
    detail = "ready"
    try:
        # Touch the repository so a misconfigured DB surfaces as not-ready.
        get_repository().metrics("__readiness_probe__")
    except Exception as exc:  # noqa: BLE001
        ready = False
        detail = f"repository unavailable: {type(exc).__name__}"
    return {
        "ready": ready,
        "storage": settings.storage,
        "llm_provider": settings.llm_provider,
        "embeddings_provider": settings.embeddings_provider,
        "embedding_dim": settings.embedding_dim,
        "detail": detail,
    }
