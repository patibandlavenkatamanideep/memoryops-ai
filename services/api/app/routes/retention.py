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

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ..auth import enforce_scope
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


def _load(req: _ScopedRequest, request: Request):
    enforce_scope(request, req.tenant_id, req.user_id)
    repo = get_repository()
    memory = repo.get_memory(req.tenant_id, req.user_id, req.memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return repo, memory


def _trace(request: Request) -> str:
    return getattr(request.state, "trace_id", "-")


def _state(memory) -> dict:
    return {"memory_id": memory.id, "governance": gov.public_governance(memory)}


# ── mutations ─────────────────────────────────────────────────────────────────
@router.post("/legal-hold")
def set_legal_hold(req: LegalHoldRequest, request: Request) -> dict:
    repo, memory = _load(req, request)
    gov.set_legal_hold(memory, on=req.on, reason=req.reason)
    with repo.transaction(req.tenant_id, req.user_id):
        repo.update_memory(memory)
        audit_service().record(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            memory_id=req.memory_id,
            action="memory_legal_hold_set" if req.on else "memory_legal_hold_released",
            reason=(req.reason or "legal hold updated") if req.on else "legal hold released",
            trace_id=_trace(request),
            metadata={"legal_hold": req.on},
        )
    return _state(memory)


@router.post("/pin")
def set_pin(req: FlagRequest, request: Request) -> dict:
    repo, memory = _load(req, request)
    gov.set_pinned(memory, on=req.on)
    with repo.transaction(req.tenant_id, req.user_id):
        repo.update_memory(memory)
        audit_service().record(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            memory_id=req.memory_id,
            action="memory_pinned" if req.on else "memory_unpinned",
            reason="memory pin updated",
            trace_id=_trace(request),
            metadata={"pinned": req.on},
        )
    return _state(memory)


@router.post("/protect")
def set_protect(req: FlagRequest, request: Request) -> dict:
    repo, memory = _load(req, request)
    gov.set_protected(memory, on=req.on)
    with repo.transaction(req.tenant_id, req.user_id):
        repo.update_memory(memory)
        audit_service().record(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            memory_id=req.memory_id,
            action="memory_protected" if req.on else "memory_unprotected",
            reason="memory protection updated",
            trace_id=_trace(request),
            metadata={"protected": req.on},
        )
    return _state(memory)


@router.post("/consent")
def set_consent(req: ConsentRequest, request: Request) -> dict:
    if req.status not in gov.ConsentStatus.ALL:
        raise HTTPException(status_code=422, detail=f"unknown consent status: {req.status}")
    repo, memory = _load(req, request)
    gov.set_consent(memory, status=req.status, expires_at=req.expires_at)
    with repo.transaction(req.tenant_id, req.user_id):
        repo.update_memory(memory)
        audit_service().record(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            memory_id=req.memory_id,
            action="memory_consent_updated",
            reason=f"consent set to {req.status}",
            trace_id=_trace(request),
            metadata={"consent_status": req.status},
        )
    return _state(memory)


# ── reads ─────────────────────────────────────────────────────────────────────
@router.get("/policies")
def list_policies() -> dict:
    return {
        "policies": [
            {"name": p.name, "description": p.description, "windows": p.windows}
            for p in available_policies()
        ]
    }


@router.get("/decisions")
def list_decisions(
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
    tenant_id: str = Query(...),
    user_id: str = Query(...),
    policy: str | None = Query(None),
) -> dict:
    repo = get_repository()
    memory = repo.get_memory(tenant_id, user_id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    decision = evaluate(memory, policy=get_policy(policy))
    return {"governance": gov.public_governance(memory), "retention_decision": decision.to_dict()}
