"""Cross-cutting observability: a dependency-free Prometheus metrics surface.

Distinct from ``app/workers/metrics.py`` (worker run-result summaries) and from
``GET /api/metrics`` (per-tenant business-metrics JSON). This package exposes
process-wide, content-free operational signals for a Prometheus/Grafana scrape at
``GET /metrics``. See ADR-015.
"""

from .instrument import (
    collect_worker_gauges,
    observe_economics,
    observe_http,
    observe_retrieval,
    record_policy_decision,
)
from .registry import REGISTRY, render_prometheus

__all__ = [
    "REGISTRY",
    "render_prometheus",
    "observe_http",
    "observe_retrieval",
    "record_policy_decision",
    "observe_economics",
    "collect_worker_gauges",
]
