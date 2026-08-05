"""Retention + legal hold + consent API (v0.10, ADR-013).

Admin/governance surface over the metadata-driven governance state in
``app/db/governance.py`` and the retention engine in ``app/services/retention.py``.
All endpoints are tenant + user scoped and append a content-free audit event for
every mutation (invariant #7). Reads never return memory text — only governance
metadata and admin-readable retention decisions.

Endpoints:
  POST /api/retention/legal-hold  — place / release a fail-closed legal hold
  POST /api/retention/pin         — pin / unpin (exempt from decay + archive)
  POST /api/retention/protect     — protect / unprotect (exempt from auto-delete)
  POST /api/retention/consent     — record consent status (granted/withdrawn/…)
  GET  /api/retention/policies    — list available retention policy packs
  GET  /api/retention/decisions   — preview retention decisions for active memory
  GET  /api/retention/memory/{id} — governance state for one memory
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ..auth import Permission, require_permission
from ..auth.principal import Principal
from ..db import governance as gov
from ..db.factory import get_repository
from ..deps import audit_service
from ..services.retention import available_policies, evaluate, get_policy

router = APIRouter(prefix="/api/retention", tags=["retention"])


# ── request models ────────────────────────────────────────────────────────────
class _ScopedRequest(BaseModel):
    tenant_id: str
    user_id: str
    memory_id: str


class LegalHoldRequest(_ScopedRequest):
    on: bool
    reason: str | None = None


class FlagRequest(_ScopedRequest):
    on: bool


class ConsentRequest(_ScopedRequest):
    status: str  # granted | withdrawn | expired | not_required
    expires_at: datetime | None = None


@dataclass(frozen=True)
class GovernedTarget:
    """The record a governance mutation will act on, and who is acting.

    `target_user_id` comes from the **stored** memory, never from the request. The
    request's `user_id` is a compatibility hint about where to look, and nothing more:
    trusting it both broke legitimate administration (an admin naming another user was
    refused by scope validation, and naming themselves found nothing) and let
    caller-controlled scope back into the trusted path.
    """

    repo: object
    memory: object
    principal: Principal | None
    tenant_id: str
    target_user_id: str
    permission: Permission

    def audit_metadata(self, **extra) -> dict:
        """Content-free evidence naming actor *and* target separately.

        `audit.user_id` stays the target for query compatibility, which is ambiguous
        on its own once an admin can act on someone else's record — "user_id: bob"
        cannot say whether Bob acted or was acted upon. Never includes the credential,
        its claims, or any memory content.
        """
        principal = self.principal
        return {
            **extra,
            "actor_id": principal.actor if principal else "development-unauthenticated",
            "actor_user_id": principal.user_id if principal else "development-unauthenticated",
            "actor_type": (
                "service_account" if principal and principal.is_service_account else "human"
            ),
            "target_user_id": self.target_user_id,
            "authorized_permission": self.permission.value,
            "acted_on_behalf_of_another_user": bool(
                principal and principal.user_id != self.target_user_id
            ),
        }


def _load_governed_target(
    req: _ScopedRequest, request: Request, permission: Permission
) -> GovernedTarget:
    """Authorize, then load the target inside the authenticated tenant.

    Authorization happens **first** — before any repository read, transaction, or
    audit append — so a refused caller leaves no trace and does no work.
    """
    principal = require_permission(request, permission)
    repo = get_repository()

    if principal is None:
        # Auth disabled: unchanged development behaviour, scoped by the request.
        tenant_id = req.tenant_id
        memory = repo.get_memory(req.tenant_id, req.user_id, req.memory_id)
    else:
        if req.tenant_id != principal.tenant_id:
            raise HTTPException(
                status_code=403, detail="request scope does not match authenticated principal"
            )
        tenant_id = principal.tenant_id
        # Tenant-scoped and user-spanning: an admin manages records they do not own,
        # and the tenant stays a predicate so another tenant's id is simply not found.
        memory = repo.get_memory_in_tenant(tenant_id, req.memory_id)

    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")

    return GovernedTarget(
        repo=repo,
        memory=memory,
        principal=principal,
        tenant_id=tenant_id,
        target_user_id=memory.user_id,
        permission=permission,
    )


def _trace(request: Request) -> str:
    return getattr(request.state, "trace_id", "-")


def _state(memory) -> dict:
    return {"memory_id": memory.id, "governance": gov.public_governance(memory)}


# ── mutations ─────────────────────────────────────────────────────────────────
@router.post("/legal-hold")
def set_legal_hold(req: LegalHoldRequest, request: Request) -> dict:
    target = _load_governed_target(req, request, Permission.RETENTION_MANAGE)
    repo, memory = target.repo, target.memory
    # Governance mutation + audit commit atomically (P0). The mutation runs inside
    # the transaction so a rollback restores the live in-memory row (see ADR-027).
    with repo.transaction(target.tenant_id, target.target_user_id):
        gov.set_legal_hold(memory, on=req.on, reason=req.reason)
        repo.update_memory(memory)
        audit_service().record(
            tenant_id=target.tenant_id,
            user_id=target.target_user_id,
            memory_id=req.memory_id,
            action="memory_legal_hold_set" if req.on else "memory_legal_hold_released",
            reason=(req.reason or "legal hold updated") if req.on else "legal hold released",
            trace_id=_trace(request),
            metadata=target.audit_metadata(**{"legal_hold": req.on}),
        )
    return _state(memory)


@router.post("/pin")
def set_pin(req: FlagRequest, request: Request) -> dict:
    target = _load_governed_target(req, request, Permission.RETENTION_MANAGE)
    repo, memory = target.repo, target.memory
    with repo.transaction(target.tenant_id, target.target_user_id):
        gov.set_pinned(memory, on=req.on)
        repo.update_memory(memory)
        audit_service().record(
            tenant_id=target.tenant_id,
            user_id=target.target_user_id,
            memory_id=req.memory_id,
            action="memory_pinned" if req.on else "memory_unpinned",
            reason="memory pin updated",
            trace_id=_trace(request),
            metadata=target.audit_metadata(**{"pinned": req.on}),
        )
    return _state(memory)


@router.post("/protect")
def set_protect(req: FlagRequest, request: Request) -> dict:
    target = _load_governed_target(req, request, Permission.RETENTION_MANAGE)
    repo, memory = target.repo, target.memory
    with repo.transaction(target.tenant_id, target.target_user_id):
        gov.set_protected(memory, on=req.on)
        repo.update_memory(memory)
        audit_service().record(
            tenant_id=target.tenant_id,
            user_id=target.target_user_id,
            memory_id=req.memory_id,
            action="memory_protected" if req.on else "memory_unprotected",
            reason="memory protection updated",
            trace_id=_trace(request),
            metadata=target.audit_metadata(**{"protected": req.on}),
        )
    return _state(memory)


@router.post("/consent")
def set_consent(req: ConsentRequest, request: Request) -> dict:
    if req.status not in gov.ConsentStatus.ALL:
        raise HTTPException(status_code=422, detail=f"unknown consent status: {req.status}")
    target = _load_governed_target(req, request, Permission.CONSENT_MANAGE)
    repo, memory = target.repo, target.memory
    with repo.transaction(target.tenant_id, target.target_user_id):
        gov.set_consent(memory, status=req.status, expires_at=req.expires_at)
        repo.update_memory(memory)
        audit_service().record(
            tenant_id=target.tenant_id,
            user_id=target.target_user_id,
            memory_id=req.memory_id,
            action="memory_consent_updated",
            reason=f"consent set to {req.status}",
            trace_id=_trace(request),
            metadata=target.audit_metadata(**{"consent_status": req.status}),
        )
    return _state(memory)


# ── reads ─────────────────────────────────────────────────────────────────────
def _retention_scope(request: Request, tenant_id: str, user_id: str) -> tuple[str, str]:
    """Authorize a retention read and return the scope to query with.

    `retention:read` is held by memory_admin as well as auditor: retention windows and
    expiry decisions are lifecycle management, which is what a memory admin is for.
    That is the deliberate difference from `evidence:read` and `traces:read:tenant`,
    which stay auditor-only — reading *what the system will forget* is not the same
    capability as reading *the record of who did what*.
    """
    principal = require_permission(request, Permission.RETENTION_READ)
    if principal is None:
        return tenant_id, user_id
    return principal.tenant_id, principal.user_id


@router.get("/policies")
def list_policies(request: Request) -> dict:
    """The available policy packs. Static configuration, but it describes how long
    this deployment keeps each sensitivity tier — operational detail an unauthorized
    caller has no reason to enumerate."""
    require_permission(request, Permission.RETENTION_READ)
    return {
        "policies": [
            {"name": p.name, "description": p.description, "windows": p.windows}
            for p in available_policies()
        ]
    }


@router.get("/decisions")
def list_decisions(
    request: Request,
    tenant_id: str = Query(...),
    user_id: str = Query(...),
    policy: str | None = Query(None),
    limit: int = Query(200, le=1000),
) -> dict:
    """Read-only preview of retention decisions for active memory in scope.

    Evaluates each active memory against the named (or default) policy pack and
    returns admin-readable decisions. Performs no deletion — this is the preview
    the retention worker would act on when enabled.
    """
    tenant_id, user_id = _retention_scope(request, tenant_id, user_id)
    repo = get_repository()
    pack = get_policy(policy)
    rows = repo.list_memories(tenant_id, user_id, status="active", include_deleted=False)[:limit]
    decisions = [evaluate(m, policy=pack).to_dict() for m in rows]
    summary: dict[str, int] = {}
    for d in decisions:
        summary[d["outcome"]] = summary.get(d["outcome"], 0) + 1
    return {
        "policy": pack.name,
        "scanned": len(decisions),
        "summary": summary,
        "decisions": decisions,
    }


@router.get("/memory/{memory_id}")
def get_memory_governance(
    memory_id: str,
    request: Request,
    tenant_id: str = Query(...),
    user_id: str = Query(...),
    policy: str | None = Query(None),
) -> dict:
    tenant_id, user_id = _retention_scope(request, tenant_id, user_id)
    repo = get_repository()
    memory = repo.get_memory(tenant_id, user_id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    decision = evaluate(memory, policy=get_policy(policy))
    return {"governance": gov.public_governance(memory), "retention_decision": decision.to_dict()}
