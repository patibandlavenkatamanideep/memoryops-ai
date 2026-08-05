"""Enterprise Evidence Layer API (v2.0, ADR-024).

Security-reviewable, tenant/user-scoped evidence over the governed lifecycle:
verifiable audit chain, per-response evidence bundles, deletion proofs, policy
reports, and lifecycle exports. Reads only — never mutates governance state.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..auth import Permission, enforce_scope, require_permission
from ..db.factory import get_repository
from ..evidence import (
    deletion_proof,
    evidence_bundle,
    lifecycle_export,
    policy_report,
    verify_audit,
)

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


def _evidence_scope(request: Request, tenant_id: str, user_id: str) -> tuple[str, str]:
    """Authorize an evidence read and return the scope to query with.

    `evidence:read` is an auditor capability. Managing memory does not imply reading
    the governance record of who managed it — an operator cleared to fix data is not
    thereby cleared to read the trail that would show them doing it.

    The scope comes back from the principal, so the caller's own values stop being
    used once the check has passed.
    """
    enforce_scope(request, tenant_id, user_id)
    principal = require_permission(request, Permission.EVIDENCE_READ)
    if principal is None:
        return tenant_id, user_id
    return principal.tenant_id, principal.user_id


@router.get("/audit/verify")
def audit_verify(request: Request, tenant_id: str = Query(...), user_id: str = Query(...)) -> dict:
    tenant_id, user_id = _evidence_scope(request, tenant_id, user_id)
    return verify_audit(get_repository(), tenant_id)


@router.get("/response/{trace_id}")
def response_bundle(
    trace_id: str, request: Request, tenant_id: str = Query(...), user_id: str = Query(...)
) -> dict:
    tenant_id, user_id = _evidence_scope(request, tenant_id, user_id)
    return evidence_bundle(get_repository(), tenant_id, user_id, trace_id)


@router.get("/deletion/{memory_id}")
def deletion_report(
    memory_id: str, request: Request, tenant_id: str = Query(...), user_id: str = Query(...)
) -> dict:
    tenant_id, user_id = _evidence_scope(request, tenant_id, user_id)
    return deletion_proof(get_repository(), tenant_id, user_id, memory_id)


@router.get("/policy")
def policy(request: Request, tenant_id: str = Query(...), user_id: str = Query(...)) -> dict:
    tenant_id, user_id = _evidence_scope(request, tenant_id, user_id)
    return policy_report(get_repository(), tenant_id, user_id)


@router.get("/lifecycle/{memory_id}")
def lifecycle(
    memory_id: str, request: Request, tenant_id: str = Query(...), user_id: str = Query(...)
) -> dict:
    tenant_id, user_id = _evidence_scope(request, tenant_id, user_id)
    return lifecycle_export(get_repository(), tenant_id, user_id, memory_id)
