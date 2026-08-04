"""GET /api/audit and GET /api/metrics — governance + observability surfaces."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..auth import Permission, require_permission
from ..auth.decisions import authorize_subject_scope
from ..db.factory import get_repository
from ..schemas.memory import AuditEvent

router = APIRouter(prefix="/api", tags=["governance"])


@router.get("/audit", response_model=list[AuditEvent])
def get_audit(
    request: Request,
    tenant_id: str = Query(...),
    user_id: str | None = Query(None),
    memory_id: str | None = Query(None),
    limit: int = Query(200, le=1000),
) -> list[AuditEvent]:
    """Audit trail, authorized per caller.

    `user_id` was optional and unauthorized, and the scope-validation middleware
    only checks a `user_id` that is *present* — so omitting it skipped validation
    and returned **tenant-wide** records to any authenticated caller. Verified with
    auth on: alice requesting `?tenant_id=acme` received bob's rows.

    A tenant-wide read now requires `audit:read:tenant`; without it the query is
    forced to the caller's own `user_id`.
    """
    subject = authorize_subject_scope(
        request,
        requested_tenant_id=tenant_id,
        requested_user_id=user_id,
        self_permission=Permission.AUDIT_READ_SELF,
        tenant_permission=Permission.AUDIT_READ_TENANT,
    )
    repo = get_repository()
    # Only the authorized scope reaches the repository — never the request values.
    rows = repo.list_audit(
        subject.tenant_id, user_id=subject.user_id, memory_id=memory_id, limit=limit
    )
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
def get_metrics(request: Request, tenant_id: str = Query(...)) -> dict:
    """Tenant-wide counts. Aggregate, but still tenant-wide — an ordinary user
    should not learn how much other users have stored."""
    require_permission(request, Permission.METRICS_READ_TENANT)
    return get_repository().metrics(tenant_id)
