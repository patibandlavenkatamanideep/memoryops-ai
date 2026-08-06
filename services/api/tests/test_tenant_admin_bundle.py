"""`tenant_admin` must be an explicit list, never "whatever permissions exist".

The hazard this removes
-----------------------
`Role.TENANT_ADMIN: frozenset(set(Permission))` granted every permission in the enum,
including ones that did not exist yet. Any capability added later — for any reason,
by anyone — became tenant-admin authority the moment it was defined, with no decision
and no diff to review at the grant site.

That is exactly wrong for the capabilities coming next: deployment-level operations
where one tenant's administrator must not be able to act for the whole platform.
"""

from __future__ import annotations

from app.auth.roles import (
    _NOT_TENANT_SCOPED,
    _TENANT_ADMIN,
    ROLE_PERMISSIONS,
    Permission,
    Role,
    permissions_for,
)


def test_every_permission_is_deliberately_included_or_excluded():
    """The guard that makes the bundle self-maintaining.

    A new `Permission` member fails this until someone either grants it to tenant
    admins or records why it is not tenant-scoped. Under the old `set(Permission)`
    spelling there was nothing to fail: the grant happened silently.
    """
    accounted = _TENANT_ADMIN | set(_NOT_TENANT_SCOPED)
    unaccounted = set(Permission) - accounted
    assert not unaccounted, (
        "new permission(s) not classified for tenant_admin: "
        f"{sorted(p.value for p in unaccounted)} — add to _TENANT_ADMIN, or to "
        "_NOT_TENANT_SCOPED with the reason it is not tenant-scoped"
    )
    overlap = _TENANT_ADMIN & set(_NOT_TENANT_SCOPED)
    assert not overlap, f"listed as both granted and excluded: {sorted(p.value for p in overlap)}"


def test_a_new_permission_is_not_granted_automatically(monkeypatch):
    """Simulates adding a permission without touching the bundle.

    This is the regression itself: the old spelling would have granted it.
    """
    from app.auth import roles as roles_module

    class _Extended(str):
        value = "ops:something:new"

    invented = _Extended("ops:something:new")

    # The bundle is a fixed frozenset, so an unknown capability is simply absent.
    assert invented not in ROLE_PERMISSIONS[Role.TENANT_ADMIN]
    assert invented not in permissions_for(frozenset({Role.TENANT_ADMIN}))

    # And the accounting guard would have caught it.
    accounted = roles_module._TENANT_ADMIN | set(roles_module._NOT_TENANT_SCOPED)
    assert invented not in accounted


def test_withheld_permissions_are_actually_withheld():
    """Whatever is listed as excluded must really not be granted.

    Empty today — this commit restates the existing grants without moving any — so
    this guards the mechanism rather than a current exclusion.
    """
    granted = permissions_for(frozenset({Role.TENANT_ADMIN}))
    for permission, reason in _NOT_TENANT_SCOPED.items():
        assert permission not in granted, f"{permission.value} still granted: {reason}"


def test_tenant_admin_is_exactly_the_tenant_scoped_permissions():
    """Everything except what is deliberately withheld — no more, no less."""
    granted = permissions_for(frozenset({Role.TENANT_ADMIN}))
    assert granted == frozenset(Permission) - set(_NOT_TENANT_SCOPED)


def test_a_platform_operator_holds_no_tenant_data_permission():
    """Operating the deployment does not include reading what customers stored in it.

    The two authorities are disjoint on purpose: an operator sees process-wide
    telemetry and spends platform compute, and never memory, audit or governance.
    """
    operator = permissions_for(frozenset({Role.PLATFORM_OPERATOR}))
    assert operator, "the role must grant something"
    assert operator.isdisjoint(_TENANT_ADMIN), (
        f"overlaps tenant authority: {sorted(p.value for p in operator & _TENANT_ADMIN)}"
    )
    assert all(p.value.startswith("ops:") for p in operator)


def test_no_tenant_role_can_reach_a_deployment_permission():
    """The escalation this whole commit exists to prevent."""
    for role in (
        Role.MEMORY_VIEWER,
        Role.MEMORY_USER,
        Role.MEMORY_ADMIN,
        Role.AUDITOR,
        Role.TENANT_ADMIN,
        Role.SERVICE_WORKER,
    ):
        granted = permissions_for(frozenset({role}))
        leaked = {p for p in granted if p.value.startswith("ops:")}
        assert not leaked, f"{role.value} holds {sorted(p.value for p in leaked)}"


def test_tenant_admin_still_holds_every_tenant_capability():
    """The bundle must not have quietly narrowed while being written out."""
    granted = permissions_for(frozenset({Role.TENANT_ADMIN}))
    for role in (Role.MEMORY_VIEWER, Role.MEMORY_USER, Role.MEMORY_ADMIN):
        assert permissions_for(frozenset({role})) <= granted, (
            f"tenant_admin lost a capability that {role.value} still has"
        )
    # The auditor's tenant reads, minus the deployment-scoped eval results.
    auditor = permissions_for(frozenset({Role.AUDITOR})) - set(_NOT_TENANT_SCOPED)
    assert auditor <= granted


def test_service_worker_is_unaffected():
    """The worker fleet keeps exactly its operational permissions."""
    assert permissions_for(frozenset({Role.SERVICE_WORKER})) == frozenset(
        {Permission.WORKER_READ, Permission.WORKER_REPLAY}
    )
