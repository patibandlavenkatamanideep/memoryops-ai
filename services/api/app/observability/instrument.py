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


def record_admission_decision(decision: str) -> None:
    try:
        m.ADMISSION_DECISIONS_TOTAL.inc({"decision": decision})
    except Exception:  # noqa: BLE001 — never break the read path
        logger.debug("record_admission_decision failed", extra={"event": "metric_drop"})


def observe_economics(econ) -> None:
    """Record advisory token + cost estimates for a request (no-throw).

    ``econ`` is a ``app.economics.RequestEconomics``. Labels are bounded
    (kind + model); no tenant/user/content ever reaches a metric.
    """
    try:
        emb_model = econ.embedding_model or "stub"
        llm_model = econ.llm_model or "stub"
        if econ.embedding_tokens:
            m.TOKENS_TOTAL.inc({"kind": "embedding", "model": emb_model}, econ.embedding_tokens)
        if econ.context_tokens:
            m.TOKENS_TOTAL.inc({"kind": "context", "model": llm_model}, econ.context_tokens)
        if econ.compressed_tokens:
            m.TOKENS_TOTAL.inc({"kind": "compressed", "model": llm_model}, econ.compressed_tokens)
        if econ.tokens_saved:
            m.TOKENS_TOTAL.inc({"kind": "saved", "model": llm_model}, econ.tokens_saved)
        if econ.llm_input_tokens:
            m.TOKENS_TOTAL.inc({"kind": "llm_input", "model": llm_model}, econ.llm_input_tokens)
        if econ.estimated_cost_usd:
            m.ESTIMATED_COST_USD_TOTAL.inc(
                {"kind": "request", "model": llm_model}, econ.estimated_cost_usd
            )
        if econ.cost_saved_usd:
            m.ESTIMATED_COST_USD_TOTAL.inc(
                {"kind": "saved", "model": llm_model}, econ.cost_saved_usd
            )
    except Exception:  # noqa: BLE001 — never break the chat path
        logger.debug("observe_economics failed", extra={"event": "metric_drop"})


def collect_worker_gauges(repo, limit: int = 500) -> None:
    """Refresh pull-derived worker gauges from persisted run history at scrape time.

    Workers run in a separate process, so their activity is not visible to the
    API's in-process counters; we read the content-free run-history summary
    instead. Best-effort — on any error (e.g. DB unavailable) the gauges are left
    cleared so ``/metrics`` degrades to omitting worker signals, never a 500.
    """
    # Import here to avoid a heavy import at module load for the common path.
    from ..db.entities import OperationalAccessUnavailable
    from ..workers.orchestrator import summarize_runtime_health

    m.WORKER_RUNS.reset()
    try:
        summary = summarize_runtime_health(repo, limit=limit)
        for status, count in summary.get("by_status", {}).items():
            m.WORKER_RUNS.set(count, {"status": status})
        m.WORKER_DEAD_LETTER.set(summary.get("dead_letter_count", 0))
        m.WORKER_FAILED.set(summary.get("failed_count", 0))
    except OperationalAccessUnavailable:
        # Expected when no operational connection is configured — leave the worker
        # gauges omitted rather than logging noise on every scrape.
        pass
    except Exception:  # noqa: BLE001 — worker metrics are best-effort
        logger.debug("collect_worker_gauges failed", extra={"event": "metric_drop"})
