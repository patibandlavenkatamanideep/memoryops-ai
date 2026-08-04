"""Memory CRUD: list, patch (edit/approve/reject/archive), delete (soft)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..auth import (
    Permission,
    authorize_loaded_resource,
    authorize_subject_scope,
    authorize_transition,
    current_principal,
    enforce_scope,
)
from ..auth.authz_spec import ROUTE_AUTHZ
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
from ..services.policy_broker import PolicyBroker
from ..services.status_transitions import (
    EDIT_FIELDS,
    TRANSITION_AUDIT,
    UNSUPPORTED_PATCH_STATUSES,
    InvalidTransition,
    UnsupportedStatus,
    derive_patch_actions,
    validate_transition,
)
from ..services.update_service import (
    LegalHoldActive,
    UpdateRejected,
    apply_content_update,
)

router = APIRouter(prefix="/api/memories", tags=["memories"])

_PATCH_SPEC = ROUTE_AUTHZ[("PATCH", "/api/memories/{memory_id}")]


def _load_in_scope(request: Request, memory_id: str, *, tenant_id: str, user_id: str):
    """Find a memory for authorization, and return the scope to trust afterwards.

    Two lookups, because the question differs. With auth **on**, ownership is not yet
    known — that is what the caller is being authorized against — so the lookup is
    tenant-scoped and spans users, and the *stored* owner becomes the scope for
    everything downstream. With auth **off** there is no principal to scope to, so the
    supplied values stand (unchanged development behaviour).

    The authenticated tenant is always part of the lookup, so a memory in another
    tenant is simply not found.
    """
    repo = get_repository()
    principal = current_principal(request)
    if principal is None:
        return repo.get_memory(tenant_id, user_id, memory_id), tenant_id, user_id
    found = repo.get_memory_in_tenant(principal.tenant_id, memory_id)
    if found is None:
        return None, tenant_id, user_id
    # The supplied `user_id` was only ever a hint about which record to find. Once the
    # record is loaded, its stored owner is the only thing that decides anything —
    # continuing to pass the caller's value would put caller-controlled input back
    # into queries that authorization has already settled, and would silently return
    # nothing when an admin legitimately reads another user's memory.
    return found, found.tenant_id, found.user_id


def _authorized_memory(
    request: Request,
    memory_id: str,
    *,
    tenant_id: str,
    user_id: str,
    self_permission: Permission,
    tenant_permission: Permission,
):
    """`_load_in_scope` plus the ownership check. 404 when absent or not permitted."""
    memory, scope_tenant, scope_user = _load_in_scope(
        request, memory_id, tenant_id=tenant_id, user_id=user_id
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    authorize_loaded_resource(
        request,
        resource_tenant_id=memory.tenant_id,
        resource_user_id=memory.user_id,
        self_permission=self_permission,
        tenant_permission=tenant_permission,
    )
    return memory, scope_tenant, scope_user


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
    # Authorize *first*, and continue on the resolved scope. A loop run or audit
    # event opened on the query-string values would record an unauthorized request
    # as a governance action that happened, under a scope nothing had checked.
    subject = authorize_subject_scope(
        request,
        requested_tenant_id=tenant_id,
        requested_user_id=user_id,
        self_permission=Permission.MEMORY_READ_SELF,
        tenant_permission=Permission.MEMORY_READ_TENANT,
    )
    tenant_id, user_id = subject.tenant_id, subject.user_id or user_id
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
    Authorization visibility is not retrieval visibility: a deleted memory is
    inspectable here and still absent from every retrieval path.
    """
    m, tenant_id, user_id = _authorized_memory(
        request,
        memory_id,
        tenant_id=tenant_id,
        user_id=user_id,
        self_permission=Permission.MEMORY_READ_SELF,
        tenant_permission=Permission.MEMORY_READ_TENANT,
    )
    trace_id = getattr(request.state, "trace_id", "-")
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
    request: Request,
    tenant_id: str = Query(...),
    user_id: str = Query(...),
    limit: int = Query(200, le=1000),
) -> list[AuditEvent]:
    """Audit timeline for one memory (newest first), tenant + user scoped.

    Reading a memory's evidence is an *audit* capability, not a memory-read one:
    the trail names who did what and when, which a memory reader is not thereby
    entitled to.
    """
    _m, tenant_id, user_id = _authorized_memory(
        request,
        memory_id,
        tenant_id=tenant_id,
        user_id=user_id,
        self_permission=Permission.AUDIT_READ_SELF,
        tenant_permission=Permission.AUDIT_READ_TENANT,
    )
    rows = get_repository().list_audit(tenant_id, user_id, memory_id=memory_id, limit=limit)
    return [_audit_event(r) for r in rows]


@router.get("/{memory_id}/provenance", response_model=MemoryProvenance)
def get_memory_provenance(
    memory_id: str,
    request: Request,
    tenant_id: str = Query(...),
    user_id: str = Query(...),
) -> MemoryProvenance:
    """Provenance + explainability for one memory (invariant #3).

    Composes the stored ``source`` with the memory's audit trail and the
    governance loop runs that touched it. Never returns embeddings or secrets.
    """
    m, tenant_id, user_id = _authorized_memory(
        request,
        memory_id,
        tenant_id=tenant_id,
        user_id=user_id,
        self_permission=Permission.MEMORY_READ_SELF,
        tenant_permission=Permission.MEMORY_READ_TENANT,
    )
    repo = get_repository()
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
    # Refuse a no-op patch before it opens a loop run and an audit trail. It asks
    # for no action, so there is no permission it could be checked against.
    if patch.changes_nothing:
        raise HTTPException(
            status_code=422,
            detail=(
                "patch requests no change: provide at least one of "
                f"{', '.join(EDIT_FIELDS)}, status"
            ),
        )
    repo = get_repository()
    trace_id = getattr(request.state, "trace_id", "-")
    m, scope_tenant, scope_user = _load_in_scope(
        request, memory_id, tenant_id=patch.tenant_id, user_id=patch.user_id
    )
    if not m or m.status == Status.deleted:
        raise HTTPException(status_code=404, detail="memory not found")

    # ── status transition validation (before any mutation) ────────────────────
    # Route-level defence in depth: even if the schema were widened again, an
    # unsupported target is refused here. `status="deleted"` previously fell
    # through the handler's elif chain and was assigned verbatim, producing a row
    # that was hidden from retrieval but had no `deleted_at`, no tombstone, no
    # lineage, and a generic `memory_updated` audit action — and it succeeded even
    # under a legal hold that the real DELETE route refuses with 409.
    transition: str | None = None
    if patch.status is not None:
        if patch.status in UNSUPPORTED_PATCH_STATUSES:
            raise HTTPException(
                status_code=422,
                detail="status must be changed through its dedicated governance workflow",
            )
        try:
            transition = validate_transition(m.status, patch.status)
        except UnsupportedStatus as exc:  # pragma: no cover - guarded above
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except InvalidTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    # ── authorize every action the body requests ──────────────────────────────
    # A PATCH is not one action. `{"content": ..., "status": "active"}` edits *and*
    # approves, and the two are governed differently — `edit` has a self permission,
    # `approve` deliberately does not. Requiring only one of them would let
    # `memory:approve:tenant` grant a content edit, so an approver could rewrite the
    # text in the request that approves it. Every action is authorized, and each
    # records its own witness.
    requested_actions = derive_patch_actions(
        has_content=patch.content is not None,
        has_importance=patch.importance is not None,
        has_confidence=patch.confidence is not None,
        transition=transition,
    )
    authorized_permissions = [
        authorize_transition(
            request,
            spec=_PATCH_SPEC,
            validated_action=act,
            resource_tenant_id=m.tenant_id,
            resource_user_id=m.user_id,
        ).permission.value
        for act in sorted(requested_actions)
    ]

    # Everything past this point runs on the authorized scope, not the body's.
    patch = patch.model_copy(update={"tenant_id": scope_tenant, "user_id": scope_user})
    loop = start_loop_run_sync(
        repo,
        LoopId.MEMORY_GOVERNANCE,
        trace_id,
        tenant_id=scope_tenant,
        user_id=scope_user,
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
        evidence={
            "tenant_scoped": True,
            "user_scoped": True,
            "requested_actions": sorted(requested_actions),
        },
    )

    # Mutation + audit are one atomic unit of work (P0): a crash mid-way can no
    # longer persist the edit without its audit evidence, or vice versa. The
    # transaction must open *before* the in-place field mutations — the in-memory
    # backend hands back the live stored row, so a rollback can only undo changes
    # made after the unit of work's snapshot is taken.
    edit_action = "memory_updated"
    edit_reason = "memory edited"
    update_evidence: dict = {}
    with repo.transaction(patch.tenant_id, patch.user_id):
        if patch.content is not None:
            # Content edits go through the governed update service (invariant #5:
            # the policy broker runs before any write). This path previously
            # assigned `patch.content` straight onto the row, so an edit could
            # introduce content that creation would have BLOCKed, kept the stale
            # sensitivity label, and left the previous embedding attached to the
            # new text.
            try:
                result = apply_content_update(
                    m,
                    patch.content,
                    broker=PolicyBroker(repo),
                    settings=repo.get_settings(patch.tenant_id, patch.user_id),
                    expected_revision=patch.expected_revision,
                )
            except LegalHoldActive as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except UpdateRejected as exc:
                raise HTTPException(status_code=422, detail=exc.reason) from exc
            edit_action, edit_reason = result.audit_action, result.reason
            update_evidence = result.evidence
        if patch.importance is not None:
            m.importance = patch.importance
        if patch.confidence is not None:
            m.confidence = patch.confidence
        if patch.status is not None and transition is not None:
            # `transition` was resolved from (current, requested) above, so the audit
            # action reflects what actually happened. The old elif chain keyed off the
            # target alone, so pending→active and archived→active were both recorded
            # as "memory_approved" — a restore was indistinguishable from an approval.
            m.status = patch.status

        # Persist. When the caller supplied `expected_revision`, the write is a
        # compare-and-swap so the *database* arbitrates concurrency — a Python-side
        # check would be a time-of-check/time-of-use race, and embedding generation
        # sits between the read and this write. `rowcount == 0` means another writer
        # got there first.
        if patch.expected_revision is not None:
            saved = repo.update_memory_checked(m, expected_revision=patch.expected_revision)
            if saved is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"memory changed since revision {patch.expected_revision}; "
                        "re-read it and retry"
                    ),
                )
            m = saved
        else:
            # No expectation supplied → last-write-wins, unchanged behaviour.
            m = repo.update_memory(m)
        if update_evidence:
            update_evidence = {**update_evidence, "revision": m.revision}

        # The action the loop reports. A transition is the headline when present,
        # matching what this route has always recorded for approve/reject/archive.
        action = TRANSITION_AUDIT[transition][0] if transition else edit_action
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

        # One audit record per action performed. A mixed edit-plus-transition used to
        # collapse into a single record — the transition overwrote the edit's action
        # and reason — so the durable evidence said "approved" about a request that
        # also rewrote the text. Both records commit inside this transaction, so the
        # pair is atomic and the hash chain stays append-only.
        provenance = {
            "requested_actions": sorted(requested_actions),
            "authorized_permissions": authorized_permissions,
            "content_updated": patch.content is not None,
            "transition": transition,
        }
        written = []
        if "edit" in requested_actions:
            written.append((edit_action, edit_reason, {**update_evidence, **provenance}))
        if transition is not None:
            t_action, t_reason = TRANSITION_AUDIT[transition]
            written.append((t_action, t_reason, dict(provenance)))
        audits = [
            audit_service().record(
                tenant_id=patch.tenant_id,
                user_id=patch.user_id,
                memory_id=memory_id,
                action=written_action,
                reason=written_reason,
                trace_id=trace_id,
                # Before/after *hashes*, the policy decision, and which permissions
                # authorized the change — never the content itself: the audit trail is
                # read by operators who may not be cleared for the memory, and a
                # deleted memory's text must not survive here.
                metadata=written_metadata,
            )
            for written_action, written_reason, written_metadata in written
        ]
        audit = audits[-1]
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.AUDITED,
        event_type="memory_governance_audited",
        reason="memory governance audit event written",
        evidence={
            "audit_event_id": audit.id,
            "action": action,
            "audit_event_ids": [a.id for a in audits],
        },
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
    # Authorize before opening the governance loop. A refused caller must not leave a
    # loop run behind — a delete attempt nobody was permitted to make is not a
    # governance action that happened. (A *permitted* delete refused by legal hold
    # still is, and is still recorded below.)
    existing, scope_tenant, scope_user = _authorized_memory(
        request,
        memory_id,
        tenant_id=body.tenant_id,
        user_id=body.user_id,
        self_permission=Permission.MEMORY_DELETE_SELF,
        tenant_permission=Permission.MEMORY_DELETE_TENANT,
    )
    body = body.model_copy(update={"tenant_id": scope_tenant, "user_id": scope_user})
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
    # leave the loop run recorded so the blocked attempt is auditable. Authorization
    # decides whether the caller may *attempt* a deletion; it never overrides a hold,
    # so this check stays after it and applies to every role including tenant admin.
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
