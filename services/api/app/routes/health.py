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
    """Readiness probe with *dependency-specific* states (v2.3).

    Rather than a single combined detail string, each backing dependency reports
    its own ``{"status": ok|error|skipped, ...}`` so an operator can see *which*
    dependency is unhealthy. Every probe is no-throw (invariant #4); the top-level
    ``ready`` is false iff any dependency is in an ``error`` state (``skipped`` —
    e.g. a backend not selected — never blocks readiness).
    """
    settings = get_settings()
    checks: dict[str, dict] = {
        "storage": _check_storage(settings),
        "schema": _check_schema(settings),
        "vector_backend": _check_vector_backend(settings),
        "worker_runtime": _check_worker_runtime(settings),
        "llm_provider": {"status": "ok", "provider": settings.llm_provider},
        "embedding_provider": {
            "status": "ok",
            "provider": settings.embeddings_provider,
            "dim": settings.embedding_dim,
        },
    }
    ready = all(c["status"] != "error" for c in checks.values())
    return {
        "ready": ready,
        "profile": settings.profile,
        "storage": settings.storage,
        "checks": checks,
    }


def _check_storage(settings) -> dict:
    try:
        # Touch the repository so a misconfigured DB/pool surfaces as not-ready.
        get_repository().metrics("__readiness_probe__")
        return {"status": "ok", "backend": settings.storage}
    except Exception as exc:  # noqa: BLE001 — readiness must not raise
        return {"status": "error", "backend": settings.storage, "detail": type(exc).__name__}


def _check_schema(settings) -> dict:
    if settings.storage != "postgres":
        return {"status": "skipped", "detail": "in-memory store has no schema revision"}
    # get_repository() validates the applied migration at construction and raises if
    # outdated; if _check_storage passed, the expected revision is applied.
    try:
        from ..db.postgres_repo import _CURRENT_SCHEMA_VERSION

        get_repository()
        return {"status": "ok", "revision": _CURRENT_SCHEMA_VERSION}
    except Exception as exc:  # noqa: BLE001 — readiness must not raise
        return {"status": "error", "detail": type(exc).__name__}


def _check_vector_backend(settings) -> dict:
    if settings.vector_index == "memory":
        return {"status": "ok", "backend": "memory"}
    # External backends degrade to keyword-only if unreachable (never fatal), so this
    # is informational: report the selected backend without failing readiness.
    return {
        "status": "ok",
        "backend": settings.vector_index,
        "note": "degrades to keyword-only if unreachable",
    }


def _check_worker_runtime(settings) -> dict:
    if not settings.operational_database_url:
        return {
            "status": "skipped",
            "detail": "operational access not configured (global worker health disabled)",
        }
    from ..db.entities import OperationalAccessUnavailable
    from ..workers.orchestrator import summarize_runtime_health

    try:
        summary = summarize_runtime_health(get_repository(), limit=1)
        return {
            "status": "ok",
            "dead_letter_count": summary.get("dead_letter_count", 0),
            "failed_count": summary.get("failed_count", 0),
        }
    except OperationalAccessUnavailable:
        return {"status": "skipped", "detail": "operational access not configured"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": type(exc).__name__}
