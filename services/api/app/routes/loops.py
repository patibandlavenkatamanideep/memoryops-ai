"""Loop engineering API surfaces."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..auth import Permission, require_authenticated, require_permission
from ..db.factory import get_repository
from ..loops.registry import get_loop_definition, list_loop_definitions
from ..loops.types import LoopDefinition, LoopEvent, LoopRun, LoopTrace

router = APIRouter(prefix="/api/loops", tags=["loops"])


def _tenant_of(request: Request, requested: str) -> str:
    """Authorize a tenant-wide loop read and return the tenant to query.

    Loop runs and events are governance evidence — who did what, when — so reading
    them tenant-wide is an auditor capability, not something an ordinary user's own
    memory access implies. Uses `audit:read:tenant` — the same capability that governs
    the audit trail, because both answer "who acted in this tenant" and splitting them
    would let one be granted without the other while exposing the same facts.

    The tenant comes back from the principal: validating the requested value and then
    querying with it would leave caller-controlled input in the query after
    authorization had settled the question.
    """
    principal = require_permission(request, Permission.AUDIT_READ_TENANT)
    return principal.tenant_id if principal is not None else requested


@router.get("", response_model=list[LoopDefinition])
def list_loops(request: Request) -> list[LoopDefinition]:
    """The six loop definitions. Static product documentation, identical for every
    caller — no tenant, user, or request state reaches them — so the contract is
    "any verified caller" and nothing narrower. Pinned by
    `tests/test_governance_read_boundary.py`, which fails if a prompt, provider name,
    environment value, or tenant identifier ever appears here."""
    require_authenticated(request)
    return list_loop_definitions()


@router.get("/runs", response_model=list[LoopRun])
def list_loop_runs(
    request: Request,
    loop_id: str | None = Query(None),
    trace_id: str | None = Query(None),
    tenant_id: str = Query(...),
    user_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(200, le=1000),
) -> list[LoopRun]:
    tenant_id = _tenant_of(request, tenant_id)
    return get_repository().list_loop_runs(
        loop_id=loop_id,
        trace_id=trace_id,
        tenant_id=tenant_id,
        user_id=user_id,
        status=status,
        limit=limit,
    )


@router.get("/events", response_model=list[LoopEvent])
def list_loop_events(
    request: Request,
    loop_run_id: str | None = Query(None),
    loop_id: str | None = Query(None),
    trace_id: str | None = Query(None),
    tenant_id: str = Query(...),
    user_id: str | None = Query(None),
    event_type: str | None = Query(None),
    limit: int = Query(500, le=2000),
) -> list[LoopEvent]:
    tenant_id = _tenant_of(request, tenant_id)
    return get_repository().list_loop_events(
        loop_run_id=loop_run_id,
        loop_id=loop_id,
        trace_id=trace_id,
        tenant_id=tenant_id,
        user_id=user_id,
        event_type=event_type,
        limit=limit,
    )


@router.get("/trace/{trace_id}", response_model=LoopTrace)
def loop_trace(
    trace_id: str,
    request: Request,
    tenant_id: str = Query(...),
    user_id: str | None = Query(None),
) -> LoopTrace:
    tenant_id = _tenant_of(request, tenant_id)
    repo = get_repository()
    return LoopTrace(
        trace_id=trace_id,
        runs=repo.list_loop_runs(trace_id=trace_id, tenant_id=tenant_id, user_id=user_id),
        events=repo.list_loop_events(trace_id=trace_id, tenant_id=tenant_id, user_id=user_id),
    )


@router.get("/{loop_id}", response_model=LoopDefinition)
def get_loop(loop_id: str, request: Request) -> LoopDefinition:
    require_authenticated(request)
    definition = get_loop_definition(loop_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="loop not found")
    return definition
