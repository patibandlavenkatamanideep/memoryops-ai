"""GET /metrics — Prometheus text exposition (process-wide, content-free).

The de-facto scrape endpoint for a Prometheus/Grafana stack. Distinct from
``GET /api/metrics`` (per-tenant business-metrics JSON). Exposes operational
signals only — HTTP traffic, retrieval, policy decisions, and pull-derived worker
run counts — with bounded, non-PII labels. See ADR-015.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from ..auth import Permission, require_permission
from ..core.config import get_settings
from ..observability import REGISTRY, collect_worker_gauges, render_prometheus

router = APIRouter(tags=["ops"])

# Prometheus text exposition content type (format version 0.0.4).
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@router.get("/metrics")
def metrics(request: Request) -> PlainTextResponse:
    """Prometheus exposition.

    Content-free and low-cardinality (no tenant or user labels), and it sits outside
    the `/api/*` boundary, so the scope middleware never covered it. Most deployments
    scrape it from a private network; where it is reachable more widely,
    `MEMORYOPS_PROTECT_METRICS_ENDPOINT=true` requires `ops:metrics` — a deployment
    capability, since the series describe the process rather than any tenant.
    """
    settings = get_settings()
    if settings.protect_metrics_endpoint:
        require_permission(request, Permission.OPS_METRICS)
    if not settings.metrics_enabled:
        return PlainTextResponse("metrics disabled\n", status_code=404)

    # Refresh pull-derived worker gauges at scrape time. Best-effort: a repository
    # error leaves worker gauges cleared and still renders the rest (invariant #4).
    try:
        from ..db.factory import get_repository

        collect_worker_gauges(get_repository(), limit=settings.worker_run_history_limit)
    except Exception:  # noqa: BLE001 — scrape must never 500 on worker-metric refresh
        pass

    return PlainTextResponse(
        render_prometheus(REGISTRY), media_type=PROMETHEUS_CONTENT_TYPE
    )
