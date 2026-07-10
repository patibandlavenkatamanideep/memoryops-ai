"""GET /api/traces — recent lifecycle spans (v1.8, ADR-022).

An in-process, content-free view of the most recent tracing spans (write / read /
admission / worker / deletion-proof stages), correlated by request/job id. Attributes
are counts, modes, and decisions only — never memory content or raw tenant/user ids —
so this is safe operational telemetry, the same signals your OpenTelemetry backend
receives when `otel_enabled` is set.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..observability import recent_spans

router = APIRouter(prefix="/api", tags=["observability"])


@router.get("/traces")
def get_traces(
    limit: int = Query(100, ge=1, le=512),
    correlation_id: str | None = Query(None, description="filter to one correlated trace"),
) -> dict:
    spans = recent_spans(limit=limit, correlation_id=correlation_id)
    return {"count": len(spans), "spans": spans}
