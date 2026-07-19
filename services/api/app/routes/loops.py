"""Loop engineering API surfaces."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..db.factory import get_repository
from ..loops.registry import get_loop_definition, list_loop_definitions
from ..loops.types import LoopDefinition, LoopEvent, LoopRun, LoopTrace

router = APIRouter(prefix="/api/loops", tags=["loops"])


@router.get("", response_model=list[LoopDefinition])
def list_loops() -> list[LoopDefinition]:
    return list_loop_definitions()


@router.get("/runs", response_model=list[LoopRun])
def list_loop_runs(
    loop_id: str | None = Query(None),
    trace_id: str | None = Query(None),
    tenant_id: str = Query(...),
    user_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(200, le=1000),
) -> list[LoopRun]:
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
    loop_run_id: str | None = Query(None),
    loop_id: str | None = Query(None),
    trace_id: str | None = Query(None),
    tenant_id: str = Query(...),
    user_id: str | None = Query(None),
    event_type: str | None = Query(None),
    limit: int = Query(500, le=2000),
) -> list[LoopEvent]:
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
    tenant_id: str = Query(...),
    user_id: str | None = Query(None),
) -> LoopTrace:
    repo = get_repository()
    return LoopTrace(
        trace_id=trace_id,
        runs=repo.list_loop_runs(trace_id=trace_id, tenant_id=tenant_id, user_id=user_id),
        events=repo.list_loop_events(trace_id=trace_id, tenant_id=tenant_id, user_id=user_id),
    )


@router.get("/{loop_id}", response_model=LoopDefinition)
def get_loop(loop_id: str) -> LoopDefinition:
    definition = get_loop_definition(loop_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="loop not found")
    return definition
