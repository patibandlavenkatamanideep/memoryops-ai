"""Liveness + readiness probes."""

from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from ..core.config import get_settings
from ..db.factory import get_repository

router = APIRouter(tags=["ops"])


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/healthz/workers")
def workers_health() -> dict:
    """Worker runtime health (v0.8): recent run history, dead-letter + failure
    counts, and the last run per scope. Content-free operational evidence."""
    from ..workers.orchestrator import summarize_runtime_health

    settings = get_settings()
    try:
        summary = summarize_runtime_health(
            get_repository(), limit=settings.worker_run_history_limit
        )
        healthy = summary["dead_letter_count"] == 0 and summary["failed_count"] == 0
        return {"healthy": healthy, **summary}
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
