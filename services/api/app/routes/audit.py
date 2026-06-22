"""GET /api/audit and GET /api/metrics — governance + observability surfaces."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..db.factory import get_repository
from ..schemas.memory import AuditEvent

router = APIRouter(prefix="/api", tags=["governance"])


@router.get("/audit", response_model=list[AuditEvent])
def get_audit(
    tenant_id: str = Query(...),
    user_id: str | None = Query(None),
    memory_id: str | None = Query(None),
    limit: int = Query(200, le=1000),
) -> list[AuditEvent]:
    repo = get_repository()
    rows = repo.list_audit(tenant_id, user_id=user_id, memory_id=memory_id, limit=limit)
    return [
        AuditEvent(
            id=r.id,
            tenant_id=r.tenant_id,
            user_id=r.user_id,
            memory_id=r.memory_id,
            action=r.action,
            reason=r.reason,
            trace_id=r.trace_id,
            metadata=r.metadata,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/metrics")
def get_metrics(tenant_id: str = Query(...)) -> dict:
    return get_repository().metrics(tenant_id)
