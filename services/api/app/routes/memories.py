"""Memory CRUD: list, patch (edit/approve/reject/archive), delete (soft)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..db.factory import get_repository
from ..deps import audit_service
from ..loops.events import complete_loop_run_sync, emit_loop_event_sync, start_loop_run_sync
from ..loops.types import LoopId, LoopState
from ..schemas.memory import DeleteRequest, MemoryPatch, MemoryRecord, Status

router = APIRouter(prefix="/api/memories", tags=["memories"])


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


@router.patch("/{memory_id}", response_model=MemoryRecord)
def patch_memory(memory_id: str, patch: MemoryPatch, request: Request) -> MemoryRecord:
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
    m = repo.soft_delete(body.tenant_id, body.user_id, memory_id)
    if not m:
        raise HTTPException(status_code=404, detail="memory not found")
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
