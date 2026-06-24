"""No-throw instrumentation helpers.

Call sites use these instead of touching the registry directly. Every helper
swallows exceptions (logged at debug) so recording a metric can never raise into
a request, read, or write path (graceful degradation, invariant #4).
"""

from __future__ import annotations

from ..core.logging import get_logger
from . import registry as m

logger = get_logger("memoryops.observability")


def _status_class(status_code: int) -> str:
    try:
        return f"{status_code // 100}xx"
    except Exception:  # noqa: BLE001
        return "5xx"


def observe_http(route: str, method: str, status_code: int, duration_ms: float) -> None:
    try:
        m.HTTP_REQUESTS_TOTAL.inc(
            {"route": route, "method": method, "status_class": _status_class(status_code)}
        )
        m.HTTP_REQUEST_DURATION_MS.observe(duration_ms, {"route": route, "method": method})
    except Exception:  # noqa: BLE001 — never break the request path
        logger.debug("observe_http failed", extra={"event": "metric_drop"})


def observe_retrieval(mode: str, duration_ms: float) -> None:
    try:
        m.RETRIEVAL_TOTAL.inc({"mode": mode})
        m.RETRIEVAL_DURATION_MS.observe(duration_ms)
    except Exception:  # noqa: BLE001
        logger.debug("observe_retrieval failed", extra={"event": "metric_drop"})


def record_policy_decision(decision: str) -> None:
    try:
        m.POLICY_DECISIONS_TOTAL.inc({"decision": decision})
    except Exception:  # noqa: BLE001
        logger.debug("record_policy_decision failed", extra={"event": "metric_drop"})


def collect_worker_gauges(repo, limit: int = 500) -> None:
    """Refresh pull-derived worker gauges from persisted run history at scrape time.

    Workers run in a separate process, so their activity is not visible to the
    API's in-process counters; we read the content-free run-history summary
    instead. Best-effort — on any error (e.g. DB unavailable) the gauges are left
    cleared so ``/metrics`` degrades to omitting worker signals, never a 500.
    """
    # Import here to avoid a heavy import at module load for the common path.
    from ..workers.orchestrator import summarize_runtime_health

    m.WORKER_RUNS.reset()
    try:
        summary = summarize_runtime_health(repo, limit=limit)
        for status, count in summary.get("by_status", {}).items():
            m.WORKER_RUNS.set(count, {"status": status})
        m.WORKER_DEAD_LETTER.set(summary.get("dead_letter_count", 0))
        m.WORKER_FAILED.set(summary.get("failed_count", 0))
    except Exception:  # noqa: BLE001 — worker metrics are best-effort
        logger.debug("collect_worker_gauges failed", extra={"event": "metric_drop"})
