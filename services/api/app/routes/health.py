"""Liveness + readiness probes."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from .. import __version__
from ..auth import Permission, require_permission
from ..core.config import get_settings
from ..db.factory import get_repository

router = APIRouter(tags=["ops"])
#: Operator surfaces live under /api/admin so they sit *inside* the authentication
#: boundary (the middleware guards `/api/*`). Anything outside it is reachable
#: unauthenticated and must never carry tenant or user identifiers.
admin_router = APIRouter(prefix="/api/admin", tags=["ops-admin"])

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
def workers_health_public() -> dict:
    """**Public** worker health: safe aggregate only.

    This endpoint sits outside the `/api/*` authentication boundary, so it is
    reachable unauthenticated. It previously returned `last_run_per_scope`, whose
    keys are built as `f"{tenant_id}:{user_id}"` — leaking the tenant and user
    identifiers of every scope the fleet had processed, to anyone who could reach
    the process.

    It now returns counts only. The detailed view, including per-scope history,
    moved to `GET /api/admin/workers/health`, which is inside the auth boundary and
    requires `worker:read`.
    """
    # Liveness only. Even aggregate run and failure counts disclose deployment
    # activity and operational condition to an unauthenticated caller, and this
    # endpoint sits outside the /api/* auth boundary. Counts, per-scope history and
    # failure reasons all live behind `worker:read` on /api/admin/workers/health.
    # Built by *selecting* one key rather than deleting others: `_worker_health_detail()`
    # returns counts on success and a `detail` naming an exception type on failure, and
    # none of that belongs to an unauthenticated caller. Selecting means a field added
    # upstream later cannot leak here by default.
    try:
        healthy = bool(_worker_health_detail().get("healthy"))
    except Exception:  # noqa: BLE001 — a liveness probe must not 500 (invariant #4)
        healthy = False
    return {"healthy": healthy}


@admin_router.get("/readiness")
def readiness_detail(request: Request) -> dict:
    """The full readiness report, for operators.

    `/readyz` narrows to a boolean in production because the detailed form is an
    unauthenticated inventory of what this installation runs — storage backend, LLM
    and embedding providers, profile, and each dependency's state. That is useful to
    whoever runs the deployment and to nobody else, so it lives here behind
    `ops:readiness` rather than being removed.
    """
    require_permission(request, Permission.OPS_READINESS)
    return _readiness_report(get_settings())


@admin_router.get("/workers/health")
def workers_health_detail(request: Request) -> dict:
    """Full worker health, including per-scope history. Requires `worker:read`."""
    require_permission(request, Permission.WORKER_READ)
    return _worker_health_detail()


def _worker_health_detail() -> dict:
    """Shared implementation. Content-free about *memory*, but scope keys identify
    tenants and users, so only the protected route returns it in full."""
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


def _readiness_report(settings) -> dict:
    """Readiness probe with *dependency-specific* states (v2.3).

    Rather than a single combined detail string, each backing dependency reports
    its own ``{"status": ok|error|skipped, ...}`` so an operator can see *which*
    dependency is unhealthy. Every probe is no-throw (invariant #4); the top-level
    ``ready`` is false iff any dependency is in an ``error`` state (``skipped`` —
    e.g. a backend not selected — never blocks readiness).

    The pre-v2.3 top-level fields (``storage``, ``llm_provider``,
    ``embeddings_provider``, ``embedding_dim``, ``detail``) are retained alongside the
    new ``profile`` + ``checks`` so the response stays additive under the ``1.x``
    compatibility promise — existing consumers keep working, new ones read ``checks``.
    """
    checks: dict[str, dict] = {
        name: _safe_check(name, probe, settings)
        for name, probe in (
            ("storage", _check_storage),
            ("schema", _check_schema),
            ("vector_backend", _check_vector_backend),
            ("worker_runtime", _check_worker_runtime),
            ("llm_provider", _check_llm_provider),
            ("embedding_provider", _check_embedding_provider),
        )
    }
    ready = all(c["status"] != "error" for c in checks.values())
    degraded = any(c["status"] == "degraded" for c in checks.values())
    errored = [name for name, c in checks.items() if c["status"] == "error"]
    if ready:
        detail = "ready (degraded)" if degraded else "ready"
    else:
        detail = "not ready: " + ", ".join(errored)
    return {
        "ready": ready,
        "degraded": degraded,
        "profile": settings.profile,
        # ── retained pre-v2.3 top-level fields (additive-compat) ──────────────
        "storage": settings.storage,
        "llm_provider": settings.llm_provider,
        "embeddings_provider": settings.embeddings_provider,
        "embedding_dim": settings.embedding_dim,
        "detail": detail,
        # ── v2.3 dependency-specific view ─────────────────────────────────────
        "checks": checks,
    }


@router.get("/readyz")
def readyz() -> dict:
    """Readiness probe.

    In **production** this reports only whether the deployment is ready. The detailed
    form names the storage backend, the LLM and embedding providers, the profile, and
    each dependency's state — an unauthenticated inventory of what this installation
    runs, which is reconnaissance rather than health. Orchestrators need the status
    code and a boolean; operators use `GET /api/admin/readiness`, which carries the
    full report behind `ops:readiness`.

    Outside production the detailed shape is unchanged, so the documented `1.x`
    fields (`storage`, `llm_provider`, `embeddings_provider`, `embedding_dim`,
    `detail`, `checks`) still serve dev, demos and the playground.
    """
    settings = get_settings()
    report = _readiness_report(settings)
    if settings.profile != "production":
        return report
    return {
        "ready": report["ready"],
        "degraded": report["degraded"],
        "detail": "ready" if report["ready"] else "not ready",
    }


# ── provider readiness ───────────────────────────────────────────────────────
# These used to report {"status": "ok"} from the *configured name* alone, so an
# operator who set MEMORYOPS_LLM_PROVIDER=openai saw a green probe whether or not a
# key or SDK was present — while every request was silently served by the stub. The
# adapters import their SDKs lazily and degrade on purpose, which is right for dev
# and for offline tests, but it must be visible rather than asserted away.
#
# Severity depends on the profile: in production a selected-but-unusable provider is
# an `error` (the deployment asked for it); in dev it is `degraded` (the fallback is
# the intended experience). Secrets and raw provider errors are never exposed —
# only a `reason_code`.
_LLM_SDK_MODULES = {
    # provider -> (module the adapter imports, install extra)
    "openai": ("openai", "openai"),
    "anthropic": ("anthropic", "anthropic"),
    # app/llm/gemini_provider.py imports `from google import genai` (google-genai).
    "gemini": ("google.genai", "gemini"),
}


def _module_missing(module: str) -> bool:
    from importlib.util import find_spec

    try:
        return find_spec(module) is None
    except (ImportError, ValueError):  # namespace/partial install
        return True


def _provider_fault(settings, reason_code: str, **extra) -> dict:
    """A selected provider that cannot actually serve: error in prod, degraded in dev."""
    status = "error" if settings.profile == "production" else "degraded"
    return {"status": status, "reason_code": reason_code, "fallback": "stub", **extra}


def _check_llm_provider(settings) -> dict:
    provider = settings.llm_provider
    if provider not in _LLM_SDK_MODULES:  # stub / heuristic
        return {"status": "ok", "provider": provider}
    module, extra = _LLM_SDK_MODULES[provider]
    key = {
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "gemini": settings.gemini_api_key,
    }[provider]
    if not key:
        return _provider_fault(settings, "missing_api_key", provider=provider)
    if _module_missing(module):
        return _provider_fault(
            settings, "sdk_not_installed", provider=provider, install_extra=extra
        )
    # Deliberately no live call: a readiness probe must stay fast and must not spend
    # tokens or rate limit on every scrape. Configuration is verified, not liveness.
    return {"status": "ok", "provider": provider, "liveness": "not_probed"}


def _check_embedding_provider(settings) -> dict:
    provider = settings.embeddings_provider
    base = {"provider": provider, "dim": settings.embedding_dim}
    if provider != "openai":
        return {"status": "ok", **base}
    if not settings.openai_api_key:
        return _provider_fault(settings, "missing_api_key", **base)
    if _module_missing("openai"):
        return _provider_fault(settings, "sdk_not_installed", install_extra="openai", **base)
    return {"status": "ok", "liveness": "not_probed", **base}


def _safe_check(name: str, probe, settings) -> dict:
    """Run one probe, converting any escape into an `error` state.

    Each probe already owns a no-throw contract, but readiness is exactly the
    endpoint an operator hits when things are broken — it must never be the thing
    that 500s. Only the exception *type* is surfaced, never its message, which could
    carry a DSN or key.
    """
    try:
        return probe(settings)
    except Exception as exc:  # noqa: BLE001 — readiness must not raise
        return {"status": "error", "reason_code": "probe_raised", "detail": type(exc).__name__}


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
    """Report whether the selected index is actually usable, not merely selected.

    This previously returned ``ok`` for every external backend with a note that it
    "degrades to keyword-only if unreachable" — so an operator running Qdrant with
    the wrong URL, or without ``qdrant-client`` installed at all, saw a green probe
    while every query silently fell back to keyword-only ranking. ``VectorIndex``
    exposes a real ``available()`` check; use it.
    """
    backend = settings.vector_index
    if backend == "memory":
        return {"status": "ok", "backend": backend}

    client_module = {
        "qdrant": "qdrant_client",
        "lancedb": "lancedb",
        "weaviate": "weaviate",
    }.get(backend)
    if client_module and _module_missing(client_module):
        return _provider_fault(
            settings,
            "client_not_installed",
            backend=backend,
            install_extra=backend,
            fallback="keyword_only",
        )

    try:
        from ..db.vector.factory import create_vector_index

        index = create_vector_index(
            backend,
            url=settings.vector_index_url,
            uri=settings.vector_index_uri,
            api_key=settings.vector_index_api_key,
            collection=settings.vector_index_collection,
        )
        if not index.available():
            return _provider_fault(
                settings, "backend_unreachable", backend=backend, fallback="keyword_only"
            )
    except Exception as exc:  # noqa: BLE001 — readiness must not raise
        return _provider_fault(
            settings,
            "probe_failed",
            backend=backend,
            fallback="keyword_only",
            detail=type(exc).__name__,
        )
    return {"status": "ok", "backend": backend}


def _check_worker_runtime(settings) -> dict:
    if not settings.operational_database_url:
        return {
            "status": "skipped",
            "detail": "operational access not configured (global worker health disabled)",
        }
    from ..db.entities import OperationalAccessUnavailable
    from ..workers.orchestrator import summarize_runtime_health

    try:
        summary = summarize_runtime_health(
            get_repository(), limit=settings.worker_run_history_limit
        )
        result = {
            "status": "ok",
            "dead_letter_count": summary.get("dead_letter_count", 0),
            "failed_count": summary.get("failed_count", 0),
        }
        # Freshness. A worker that died silently kept reporting `ok` here forever,
        # because the check only asked whether *past* runs had failed — never
        # whether the worker was still running at all. Stale beyond a few intervals
        # means lifecycle work (decay, retention, compaction) has stopped.
        staleness = _worker_staleness_seconds(summary)
        if staleness is None:
            result.update(status="degraded", reason_code="no_runs_recorded")
            return result
        result["last_run_age_seconds"] = round(staleness)
        budget = max(settings.worker_interval_seconds, 1) * _STALE_INTERVALS
        result["stale_after_seconds"] = budget
        if staleness > budget:
            result.update(status="error", reason_code="worker_heartbeat_stale")
        elif summary.get("dead_letter_count", 0) > 0:
            # Dead-lettered work is real, replayable work that was given up on.
            result.update(status="degraded", reason_code="dead_lettered_jobs")
        return result
    except OperationalAccessUnavailable:
        return {"status": "skipped", "detail": "operational access not configured"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": type(exc).__name__}


# How many scheduling intervals may pass with no worker run before the runtime is
# considered stale. Three tolerates one missed pass plus jitter without flapping.
_STALE_INTERVALS = 3


def _worker_staleness_seconds(summary: dict) -> float | None:
    """Age of the most recent run across scopes, or None when nothing has run."""
    from datetime import UTC, datetime

    newest: datetime | None = None
    for entry in summary.get("last_run_per_scope", {}).values():
        raw = entry.get("started_at")
        if not raw:
            continue
        try:
            started = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if newest is None or started > newest:
            newest = started
    if newest is None:
        return None
    return (datetime.now(UTC) - newest).total_seconds()
