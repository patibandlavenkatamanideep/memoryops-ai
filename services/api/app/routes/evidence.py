"""Enterprise Evidence Layer API (v2.0, ADR-024).

Security-reviewable, tenant/user-scoped evidence over the governed lifecycle:
verifiable audit chain, per-response evidence bundles, deletion proofs, policy
reports, and lifecycle exports. Reads only — never mutates governance state.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..auth import enforce_scope
from ..db.factory import get_repository
from ..evidence import (
    deletion_proof,
    evidence_bundle,
    lifecycle_export,
    policy_report,
    verify_audit,
)

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


@router.get("/audit/verify")
def audit_verify(request: Request, tenant_id: str = Query(...), user_id: str = Query(...)) -> dict:
    enforce_scope(request, tenant_id, user_id)
    return verify_audit(get_repository(), tenant_id)


@router.get("/response/{trace_id}")
def response_bundle(
    trace_id: str, request: Request, tenant_id: str = Query(...), user_id: str = Query(...)
) -> dict:
    enforce_scope(request, tenant_id, user_id)
    return evidence_bundle(get_repository(), tenant_id, user_id, trace_id)


@router.get("/deletion/{memory_id}")
def deletion_report(
    memory_id: str, request: Request, tenant_id: str = Query(...), user_id: str = Query(...)
) -> dict:
    enforce_scope(request, tenant_id, user_id)
    return deletion_proof(get_repository(), tenant_id, user_id, memory_id)


@router.get("/policy")
def policy(request: Request, tenant_id: str = Query(...), user_id: str = Query(...)) -> dict:
    enforce_scope(request, tenant_id, user_id)
    return policy_report(get_repository(), tenant_id, user_id)


@router.get("/lifecycle/{memory_id}")
def lifecycle(
    memory_id: str, request: Request, tenant_id: str = Query(...), user_id: str = Query(...)
) -> dict:
    enforce_scope(request, tenant_id, user_id)
    return lifecycle_export(get_repository(), tenant_id, user_id, memory_id)
