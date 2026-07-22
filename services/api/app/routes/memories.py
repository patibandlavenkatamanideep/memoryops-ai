"""Memory CRUD: list, patch (edit/approve/reject/archive), delete (soft)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..auth import enforce_scope
from ..db import governance as gov
from ..db import lineage
from ..db.entities import StoredAudit
from ..db.factory import get_repository
from ..deps import audit_service
from ..loops.events import complete_loop_run_sync, emit_loop_event_sync, start_loop_run_sync
from ..loops.types import LoopId, LoopState
from ..schemas.memory import (
    AuditEvent,
    DeleteRequest,
    MemoryPatch,
    MemoryProvenance,
    MemoryRecord,
    Status,
)

router = APIRouter(prefix="/api/memories", tags=["memories"])


def _audit_event(r: StoredAudit) -> AuditEvent:
    return AuditEvent(
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


@router.get("", response_model=list[MemoryRecord])
def list_memories(
    request: Request,
    tenant_id: str = Query(...),
    user_id: str = Query(...),
    status: str | None = Query(None),
    memory_type: str | None = Query(None),
) -> list[MemoryRecord]:
    repo = get_repository()
    trace_id = getattr(request.state, "trace_id", "-")
    loop = start_loop_run_sync(
        repo,
        LoopId.MEMORY_GOVERNANCE,
        trace_id,
        tenant_id=tenant_id,
        user_id=user_id,
        metadata={"action": "view"},
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.OBSERVED,
        event_type="memory_governance_observed",
        reason="memory view requested",
        evidence={"status_filter": status or "any", "memory_type_filter": memory_type or "any"},
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.POLICY_CHECKED,
        event_type="memory_governance_policy_checked",
        reason="tenant/user scope checked for memory view",
        evidence={"tenant_scoped": True, "user_scoped": True},
    )
    rows = repo.list_memories(
        tenant_id, user_id, status=status, memory_type=memory_type
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.EXECUTED,
        event_type="memory_governance_executed",
        reason="memory view executed",
        evidence={"row_count": len(rows)},
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.VERIFIED,
        event_type="memory_governance_verified",
        reason="memory view results verified as scoped",
        evidence={"row_count": len(rows)},
    )
    audit = audit_service().record(
        tenant_id=tenant_id,
        user_id=user_id,
        action="memory_viewed",
        reason="memory list/source viewed",
        trace_id=trace_id,
        metadata={"row_count": len(rows)},
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.AUDITED,
        event_type="memory_governance_audited",
        reason="memory view audit event written",
        evidence={"audit_event_id": audit.id},
        audit_event_id=audit.id,
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.COMPLETED,
        event_type="memory_governance_completed",
        reason="memory governance view loop completed",
        evidence={"action": "view"},
    )
    complete_loop_run_sync(repo, loop, metadata={"action": "view", "row_count": len(rows)})
    return [r.to_schema() for r in rows]


@router.get("/{memory_id}", response_model=MemoryRecord)
def get_memory_detail(
    memory_id: str,
    request: Request,
    tenant_id: str = Query(...),
    user_id: str = Query(...),
) -> MemoryRecord:
    """Single memory detail for the control plane.

    Tenant + user scoped (invariant #1). Returns the row including soft-deleted
    ones for governance/forensics — callers render the real ``status`` and must
    never present a deleted row as active (the ``status`` field carries truth).
    """
    repo = get_repository()
    trace_id = getattr(request.state, "trace_id", "-")
    m = repo.get_memory(tenant_id, user_id, memory_id)
    if not m:
        raise HTTPException(status_code=404, detail="memory not found")
    audit_service().record(
        tenant_id=tenant_id,
        user_id=user_id,
        memory_id=memory_id,
        action="memory_viewed",
        reason="memory detail viewed",
        trace_id=trace_id,
        metadata={"surface": "detail"},
    )
    return m.to_schema()


@router.get("/{memory_id}/audit", response_model=list[AuditEvent])
def get_memory_audit(
    memory_id: str,
    tenant_id: str = Query(...),
    user_id: str = Query(...),
    limit: int = Query(200, le=1000),
) -> list[AuditEvent]:
    """Audit timeline for one memory (newest first), tenant + user scoped."""
    repo = get_repository()
    if not repo.get_memory(tenant_id, user_id, memory_id):
        raise HTTPException(status_code=404, detail="memory not found")
    rows = repo.list_audit(tenant_id, user_id, memory_id=memory_id, limit=limit)
    return [_audit_event(r) for r in rows]


@router.get("/{memory_id}/provenance", response_model=MemoryProvenance)
def get_memory_provenance(
    memory_id: str,
    tenant_id: str = Query(...),
    user_id: str = Query(...),
) -> MemoryProvenance:
    """Provenance + explainability for one memory (invariant #3).

    Composes the stored ``source`` with the memory's audit trail and the
    governance loop runs that touched it. Never returns embeddings or secrets.
    """
    repo = get_repository()
    m = repo.get_memory(tenant_id, user_id, memory_id)
    if not m:
        raise HTTPException(status_code=404, detail="memory not found")
    audit_rows = repo.list_audit(tenant_id, user_id, memory_id=memory_id, limit=1000)
    runs = repo.list_loop_runs(tenant_id=tenant_id, user_id=user_id, limit=1000)
    loop_run_ids = [r.id for r in runs if (r.metadata or {}).get("memory_id") == memory_id]
    return MemoryProvenance(
        memory_id=m.id,
        source=m.source,
        status=m.status,
        created_at=m.created_at,
        updated_at=m.updated_at,
        reinforcement_count=m.reinforcement_count,
        importance=m.importance,
        confidence=m.confidence,
        weight=m.weight,
        audit_trail=[_audit_event(r) for r in audit_rows],
        loop_run_ids=loop_run_ids,
    )


@router.patch("/{memory_id}", response_model=MemoryRecord)
def patch_memory(memory_id: str, patch: MemoryPatch, request: Request) -> MemoryRecord:
    # Scope lives in the body, so the query-string middleware can't guard it —
    # enforce it here (invariant #1). No-op when auth is disabled.
    enforce_scope(request, patch.tenant_id, patch.user_id)
    repo = get_repository()
    trace_id = getattr(request.state, "trace_id", "-")
    loop = start_loop_run_sync(
        repo,
        LoopId.MEMORY_GOVERNANCE,
        trace_id,
        tenant_id=patch.tenant_id,
        user_id=patch.user_id,
        metadata={"action": "patch", "memory_id": memory_id},
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.OBSERVED,
        event_type="memory_governance_observed",
        reason="memory governance patch requested",
        evidence={"has_content_patch": patch.content is not None, "status": patch.status},
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.POLICY_CHECKED,
        event_type="memory_governance_policy_checked",
        reason="memory owner/scope checked for patch",
        evidence={"tenant_scoped": True, "user_scoped": True},
    )
    m = repo.get_memory(patch.tenant_id, patch.user_id, memory_id)
    if not m or m.status == Status.deleted:
        raise HTTPException(status_code=404, detail="memory not found")

    action = "memory_updated"
    reason = "memory edited"
    if patch.content is not None:
        m.content = patch.content
        m.normalized_content = " ".join(patch.content.lower().split())
    if patch.importance is not None:
        m.importance = patch.importance
    if patch.confidence is not None:
        m.confidence = patch.confidence
    if patch.status is not None:
        m.status = patch.status
        if patch.status == Status.active:
            action, reason = "memory_approved", "pending memory approved"
        elif patch.status == Status.rejected:
            action, reason = "memory_rejected", "pending memory rejected"
        elif patch.status == Status.archived:
            action, reason = "memory_archived", "memory archived"

    # Mutation + audit are one atomic unit of work (P0): a crash mid-way can no
    # longer persist the edit without its audit evidence, or vice versa.
    with repo.transaction(patch.tenant_id, patch.user_id):
        repo.update_memory(m)
        emit_loop_event_sync(
            repo,
            loop,
            LoopState.EXECUTED,
            event_type="memory_governance_executed",
            reason="memory governance patch executed",
            evidence={"action": action, "status": m.status.value},
        )
        emit_loop_event_sync(
            repo,
            loop,
            LoopState.VERIFIED,
            event_type="memory_governance_verified",
            reason="memory status/content update verified",
            evidence={"memory_id": memory_id, "status": m.status.value},
        )
        audit = audit_service().record(
            tenant_id=patch.tenant_id,
            user_id=patch.user_id,
            memory_id=memory_id,
            action=action,
            reason=reason,
            trace_id=trace_id,
        )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.AUDITED,
        event_type="memory_governance_audited",
        reason="memory governance audit event written",
        evidence={"audit_event_id": audit.id, "action": action},
        audit_event_id=audit.id,
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.COMPLETED,
        event_type="memory_governance_completed",
        reason="memory governance patch loop completed",
        evidence={"action": action},
    )
    complete_loop_run_sync(repo, loop, metadata={"action": action, "memory_id": memory_id})
    return m.to_schema()


@router.delete("/{memory_id}")
def delete_memory(memory_id: str, body: DeleteRequest, request: Request) -> dict:
    # Scope lives in the body, so the query-string middleware can't guard it —
    # enforce it here (invariant #1). No-op when auth is disabled.
    enforce_scope(request, body.tenant_id, body.user_id)
    repo = get_repository()
    trace_id = getattr(request.state, "trace_id", "-")
    loop = start_loop_run_sync(
        repo,
        LoopId.MEMORY_GOVERNANCE,
        trace_id,
        tenant_id=body.tenant_id,
        user_id=body.user_id,
        metadata={"action": "delete", "memory_id": memory_id},
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.OBSERVED,
        event_type="memory_governance_observed",
        reason="memory delete requested",
        evidence={"memory_id": memory_id},
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.POLICY_CHECKED,
        event_type="memory_governance_policy_checked",
        reason="memory owner/scope checked for delete",
        evidence={"tenant_scoped": True, "user_scoped": True},
    )
    # Legal hold (v0.10) is fail-closed: a held memory cannot be deleted —
    # manually or by a worker — until the hold is released. Refuse with 409 and
    # leave the loop run recorded so the blocked attempt is auditable.
    existing = repo.get_memory(body.tenant_id, body.user_id, memory_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="memory not found")
    if gov.is_legal_hold(existing):
        emit_loop_event_sync(
            repo,
            loop,
            LoopState.FAILED,
            event_type="memory_governance_blocked",
            reason="delete blocked: memory under legal hold",
            evidence={"memory_id": memory_id, "legal_hold": True},
        )
        audit_service().record(
            tenant_id=body.tenant_id,
            user_id=body.user_id,
            memory_id=memory_id,
            action="memory_legal_hold_delete_blocked",
            reason="delete refused; memory under legal hold",
            trace_id=trace_id,
        )
        raise HTTPException(status_code=409, detail="memory is under legal hold")
    # Soft-deletion, tombstone stamping, and the audit event are one atomic unit
    # of work (P0): the deletion guarantee and its evidence commit together or
    # not at all. Tombstone lineage (v1.4, ADR-018) stamps an explicit, audited
    # tombstone so any artifact derived from this memory is blocked from context
    # by the admission gate; soft-deletion alone already blocks direct retrieval.
    with repo.transaction(body.tenant_id, body.user_id):
        m = repo.soft_delete(body.tenant_id, body.user_id, memory_id)
        if not m:
            raise HTTPException(status_code=404, detail="memory not found")
        lineage.set_tombstone(m, on=True, reason="memory deleted")
        repo.update_memory(m)
        emit_loop_event_sync(
            repo,
            loop,
            LoopState.EXECUTED,
            event_type="memory_governance_executed",
            reason="memory soft delete executed",
            evidence={"memory_id": memory_id, "status": "deleted"},
        )
        emit_loop_event_sync(
            repo,
            loop,
            LoopState.VERIFIED,
            event_type="memory_governance_verified",
            reason="deleted memory marked unretrievable",
            evidence={"memory_id": memory_id, "status": m.status.value},
        )
        audit = audit_service().record(
            tenant_id=body.tenant_id,
            user_id=body.user_id,
            memory_id=memory_id,
            action="memory_deleted",
            reason="memory soft-deleted; excluded from all future retrieval",
            trace_id=trace_id,
        )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.AUDITED,
        event_type="memory_governance_audited",
        reason="memory delete audit event written",
        evidence={"audit_event_id": audit.id},
        audit_event_id=audit.id,
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.COMPLETED,
        event_type="memory_governance_completed",
        reason="memory governance delete loop completed",
        evidence={"action": "memory_deleted"},
    )
    complete_loop_run_sync(
        repo,
        loop,
        metadata={"action": "memory_deleted", "memory_id": memory_id},
    )
    return {"id": memory_id, "status": "deleted"}
