"""The four authorization helpers, and the witness each records.

Separate helpers rather than one with many optional arguments: a fixed capability,
a requested subject, a loaded record, and an action-determined permission are four
different questions. One signature covering all four makes every call site look
plausible while doing something subtly different.

Each test asserts both the *decision* and the *evidence* — a handler that stopped
checking would still return the right answer for an authorized caller, so the
witness is what distinguishes "allowed" from "actually checked".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.auth.authz_spec import ROUTE_AUTHZ
from app.auth.decisions import (
    authorize_loaded_resource,
    authorize_subject_scope,
    authorize_transition,
)
from app.auth.principal import Principal
from app.auth.roles import Permission, Role
from app.auth.witness import witness_for

_PATCH_SPEC = ROUTE_AUTHZ[("PATCH", "/api/memories/{memory_id}")]


def _request(principal: Principal | None, path: str = "/api/memories/{memory_id}", method="PATCH"):
    class _Route:
        pass

    _Route.path = path
    return SimpleNamespace(
        method=method,
        state=SimpleNamespace(principal=principal),
        scope={"route": _Route()},
    )


def _principal(user: str = "alice", roles: set[Role] | None = None) -> Principal:
    return Principal(
        tenant_id="acme",
        user_id=user,
        provider="jwt",
        roles=frozenset(roles or {Role.MEMORY_USER}),
        role_claim_present=True,
    )


# ── authorize_subject_scope ──────────────────────────────────────────────────
def test_subject_scope_forces_the_query_to_the_caller():
    """Returning the caller's own requested values would leave untrusted input in
    the query path — validating a value is not the same as trusting it."""
    request = _request(_principal(), path="/api/audit", method="GET")
    subject = authorize_subject_scope(
        request,
        requested_tenant_id="acme",
        requested_user_id="alice",
        self_permission=Permission.AUDIT_READ_SELF,
        tenant_permission=Permission.AUDIT_READ_TENANT,
    )
    assert subject.user_id == "alice"
    assert subject.tenant_scoped is False

    decision = witness_for(request).decisions[0]
    assert decision.helper == "subject"
    assert decision.permission is Permission.AUDIT_READ_SELF
    assert decision.tenant_scoped is False


def test_an_omitted_subject_is_a_tenant_wide_request_not_an_implicit_self_scope():
    """A deliberate choice, and the one place this helper diverges from the
    obvious reading of "omitted -> force principal.user_id".

    Omitting the subject is how /api/audit silently returned tenant-wide records:
    the scope middleware only validates a `user_id` that is *present*. Treating an
    omitted subject as "my own" would make the request succeed with narrower data
    instead of failing — friendlier, but it silently reinterprets what the caller
    asked for, and it would change the shipped 403 that #115 established.

    Fail closed: an unscoped request is a tenant-wide request and needs the
    tenant permission. Callers wanting their own rows name themselves.
    """
    request = _request(_principal(), path="/api/audit", method="GET")
    with pytest.raises(HTTPException) as exc:
        authorize_subject_scope(
            request,
            requested_tenant_id="acme",
            requested_user_id=None,
            self_permission=Permission.AUDIT_READ_SELF,
            tenant_permission=Permission.AUDIT_READ_TENANT,
        )
    assert exc.value.status_code == 403
    assert "audit:read:tenant" in exc.value.detail


def test_subject_scope_requires_the_tenant_permission_for_another_user():
    request = _request(_principal(roles={Role.AUDITOR}), path="/api/audit", method="GET")
    subject = authorize_subject_scope(
        request,
        requested_tenant_id="acme",
        requested_user_id="bob",
        self_permission=Permission.AUDIT_READ_SELF,
        tenant_permission=Permission.AUDIT_READ_TENANT,
    )
    assert subject.user_id == "bob"
    assert subject.tenant_scoped is True

    decision = witness_for(request).decisions[0]
    assert decision.permission is Permission.AUDIT_READ_TENANT
    assert decision.tenant_scoped is True


def test_subject_scope_refuses_another_user_without_the_tenant_permission():
    request = _request(_principal(), path="/api/audit", method="GET")
    with pytest.raises(HTTPException) as exc:
        authorize_subject_scope(
            request,
            requested_tenant_id="acme",
            requested_user_id="bob",
            self_permission=Permission.AUDIT_READ_SELF,
            tenant_permission=Permission.AUDIT_READ_TENANT,
        )
    assert exc.value.status_code == 403
    assert not witness_for(request), "a refused check must not record a success"


def test_subject_scope_refuses_another_tenant():
    request = _request(_principal(roles={Role.TENANT_ADMIN}), path="/api/audit", method="GET")
    with pytest.raises(HTTPException) as exc:
        authorize_subject_scope(
            request,
            requested_tenant_id="evilcorp",
            requested_user_id=None,
            self_permission=Permission.AUDIT_READ_SELF,
            tenant_permission=Permission.AUDIT_READ_TENANT,
        )
    assert exc.value.status_code == 403


# ── authorize_loaded_resource ────────────────────────────────────────────────
def test_loaded_resource_uses_the_self_permission_for_an_owned_record():
    request = _request(_principal())
    decision = authorize_loaded_resource(
        request,
        resource_tenant_id="acme",
        resource_user_id="alice",
        self_permission=Permission.MEMORY_WRITE_SELF,
        tenant_permission=Permission.MEMORY_WRITE_TENANT,
    )
    assert decision.permission is Permission.MEMORY_WRITE_SELF
    assert decision.tenant_scoped is False
    assert witness_for(request).decisions[0].helper == "resource"


def test_loaded_resource_uses_the_tenant_permission_for_another_users_record():
    request = _request(_principal(roles={Role.MEMORY_ADMIN}))
    decision = authorize_loaded_resource(
        request,
        resource_tenant_id="acme",
        resource_user_id="bob",
        self_permission=Permission.MEMORY_WRITE_SELF,
        tenant_permission=Permission.MEMORY_WRITE_TENANT,
    )
    assert decision.permission is Permission.MEMORY_WRITE_TENANT
    assert decision.tenant_scoped is True


def test_another_users_record_is_concealed_rather_than_refused():
    """403 confirms the record exists. For an individual resource that is a leak."""
    request = _request(_principal())
    with pytest.raises(HTTPException) as exc:
        authorize_loaded_resource(
            request,
            resource_tenant_id="acme",
            resource_user_id="bob",
            self_permission=Permission.MEMORY_WRITE_SELF,
            tenant_permission=Permission.MEMORY_WRITE_TENANT,
        )
    assert exc.value.status_code == 404


def test_a_cross_tenant_record_is_concealed():
    request = _request(_principal(roles={Role.TENANT_ADMIN}))
    with pytest.raises(HTTPException) as exc:
        authorize_loaded_resource(
            request,
            resource_tenant_id="evilcorp",
            resource_user_id="alice",
            self_permission=Permission.MEMORY_WRITE_SELF,
            tenant_permission=Permission.MEMORY_WRITE_TENANT,
        )
    assert exc.value.status_code == 404


def test_ownership_does_not_grant_a_tenant_only_action():
    """The rule that makes the contract work.

    `approve` declares no self permission. Owning the record must not be read as
    "own record, therefore allowed" — a user approving their own pending sensitive
    memory would defeat the queue that put it there.
    """
    request = _request(_principal())  # memory_user, owns the record
    with pytest.raises(HTTPException) as exc:
        authorize_loaded_resource(
            request,
            resource_tenant_id="acme",
            resource_user_id="alice",
            self_permission=None,
            tenant_permission=Permission.MEMORY_APPROVE_TENANT,
            action="approve",
        )
    assert exc.value.status_code == 403
    assert not witness_for(request)


def test_a_tenant_only_action_succeeds_with_the_tenant_permission():
    request = _request(_principal(roles={Role.MEMORY_ADMIN}))
    decision = authorize_loaded_resource(
        request,
        resource_tenant_id="acme",
        resource_user_id="alice",
        self_permission=None,
        tenant_permission=Permission.MEMORY_APPROVE_TENANT,
        action="approve",
    )
    assert decision.permission is Permission.MEMORY_APPROVE_TENANT
    # Recorded as tenant-scoped even though the record is the caller's own.
    assert decision.tenant_scoped is True


# ── authorize_transition ─────────────────────────────────────────────────────
def test_transition_selects_the_variant_and_records_the_action():
    request = _request(_principal(roles={Role.MEMORY_ADMIN}))
    decision = authorize_transition(
        request,
        spec=_PATCH_SPEC,
        validated_action="archive",
        resource_tenant_id="acme",
        resource_user_id="alice",
    )
    assert decision.permission is Permission.MEMORY_ARCHIVE_SELF
    actions = {d.action for d in witness_for(request).decisions}
    assert "archive" in actions
    assert any(d.helper == "transition" for d in witness_for(request).decisions)


def test_self_approval_is_refused_through_the_transition_helper():
    request = _request(_principal())
    with pytest.raises(HTTPException) as exc:
        authorize_transition(
            request,
            spec=_PATCH_SPEC,
            validated_action="approve",
            resource_tenant_id="acme",
            resource_user_id="alice",
        )
    assert exc.value.status_code == 403


def test_an_undeclared_action_fails_closed_as_a_contract_error():
    """A handler deriving an action the route never declared is a bug in us, not a
    caller error — and must not fall back to a route-level permission."""
    request = _request(_principal(roles={Role.TENANT_ADMIN}))
    with pytest.raises(HTTPException) as exc:
        authorize_transition(
            request,
            spec=_PATCH_SPEC,
            validated_action="obliterate",
            resource_tenant_id="acme",
            resource_user_id="alice",
        )
    assert exc.value.status_code == 500


def test_a_mixed_patch_records_one_decision_per_action():
    """`{"content": ..., "status": "active"}` is edit + approve, not one action.

    Authorizing only the transition would let an approve permission implicitly grant
    the content edit.
    """
    request = _request(_principal(roles={Role.MEMORY_ADMIN}))
    for action in ("edit", "approve"):
        authorize_transition(
            request,
            spec=_PATCH_SPEC,
            validated_action=action,
            resource_tenant_id="acme",
            resource_user_id="alice",
        )
    recorded = {d.action for d in witness_for(request).decisions if d.helper == "transition"}
    assert recorded == {"edit", "approve"}


def test_a_mixed_patch_is_refused_when_only_one_permission_is_held():
    """memory_user may edit its own record but may not approve it."""
    request = _request(_principal())
    authorize_transition(
        request,
        spec=_PATCH_SPEC,
        validated_action="edit",
        resource_tenant_id="acme",
        resource_user_id="alice",
    )
    with pytest.raises(HTTPException):
        authorize_transition(
            request,
            spec=_PATCH_SPEC,
            validated_action="approve",
            resource_tenant_id="acme",
            resource_user_id="alice",
        )


# ── no evidence before a decision ────────────────────────────────────────────
def test_no_witness_exists_before_any_helper_runs():
    request = _request(_principal())
    assert not witness_for(request)
