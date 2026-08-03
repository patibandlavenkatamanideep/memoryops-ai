"""API-level authorization: the boundary a direct caller cannot bypass.

The gap
-------
The API authenticated callers but never authorized them. `Principal` carried
`tenant_id`, `user_id`, `provider`, `claims` — no role, no permission.

Reproduced with authentication **on** (`MEMORYOPS_AUTH_MODE=trusted_header`):

    alice GET /api/audit?tenant_id=acme    -> 200
    audit rows returned for users: {'alice', 'bob'}

An ordinary user read another user's audit trail inside their tenant. The
scope-validation middleware only checks a `user_id` that is *present*, so omitting
it skipped validation entirely and the route defaulted to tenant-wide.

The web control plane added role checks, but they live in the Next.js BFF. A caller
talking to the API directly bypasses all of them — which is why these tests drive
the API directly rather than through the BFF.
"""

from __future__ import annotations

import pytest

from app.auth.roles import (
    DEFAULT_ROLE,
    ROLE_PERMISSIONS,
    Permission,
    Role,
    parse_roles,
    permissions_for,
)


# ── principal / role model ───────────────────────────────────────────────────
def test_unrecognised_role_names_are_ignored_not_trusted():
    """A typo or an issuer's own vocabulary must never escalate."""
    assert parse_roles("admin") == frozenset()
    assert parse_roles("superuser tenant_admin") == frozenset({Role.TENANT_ADMIN})
    assert parse_roles(["auditor", "root"]) == frozenset({Role.AUDITOR})
    assert parse_roles(None) == frozenset()
    assert parse_roles(12345) == frozenset()


def test_roles_parse_from_list_or_delimited_string():
    expected = frozenset({Role.AUDITOR, Role.MEMORY_ADMIN})
    assert parse_roles(["auditor", "memory_admin"]) == expected
    assert parse_roles("auditor memory_admin") == expected
    assert parse_roles("auditor,memory_admin") == expected


def test_an_authenticated_caller_without_roles_gets_least_privilege():
    from app.auth.principal import Principal

    p = Principal(tenant_id="t", user_id="u", provider="jwt")
    assert p.effective_roles == frozenset({DEFAULT_ROLE})
    assert p.has(Permission.MEMORY_READ_SELF)
    assert p.has(Permission.MEMORY_WRITE_SELF)
    # Never a tenant-wide or administrative default.
    assert not p.has(Permission.AUDIT_READ_TENANT)
    assert not p.has(Permission.RETENTION_MANAGE)
    assert not p.has(Permission.MEMORY_DELETE)


def test_auditor_can_read_tenant_evidence_but_not_mutate_memory():
    """An auditor who can edit what they audit is not an auditor."""
    granted = permissions_for(frozenset({Role.AUDITOR}))
    assert Permission.AUDIT_READ_TENANT in granted
    assert Permission.EVIDENCE_READ in granted
    assert Permission.METRICS_READ_TENANT in granted
    for denied in (
        Permission.MEMORY_DELETE,
        Permission.MEMORY_APPROVE,
        Permission.RETENTION_MANAGE,
        Permission.CONSENT_MANAGE,
        Permission.MEMORY_WRITE_SELF,
    ):
        assert denied not in granted, f"auditor must not hold {denied.value}"


def test_service_worker_is_operational_only():
    granted = permissions_for(frozenset({Role.SERVICE_WORKER}))
    assert granted == frozenset({Permission.WORKER_READ, Permission.WORKER_REPLAY})
    assert Permission.MEMORY_READ_SELF not in granted


def test_tenant_admin_holds_every_permission():
    assert permissions_for(frozenset({Role.TENANT_ADMIN})) == frozenset(Permission)


def test_every_role_is_mapped():
    for role in Role:
        assert role in ROLE_PERMISSIONS, f"{role.value} has no permission mapping"


# ── the audit endpoint ───────────────────────────────────────────────────────
def _hdr(user: str, roles: str | None = None, tenant: str = "acme") -> dict:
    h = {"X-MemoryOps-Tenant": tenant, "X-MemoryOps-User": user}
    if roles:
        h["X-MemoryOps-Roles"] = roles
    return h


@pytest.fixture
def rbac_client(monkeypatch):
    """A client with trusted-header auth *and* role headers enabled.

    Mirrors `auth_client` in test_auth.py: clear the cached settings/repo/service
    singletons, set the env, then import the app. Reloading the app module instead
    leaked auth state into unrelated tests.
    """
    from app import deps
    from app.core import config
    from app.db import factory

    def _clear():
        config.get_settings.cache_clear()
        factory.get_repository.cache_clear()
        deps.gateway.cache_clear()
        deps.audit_service.cache_clear()

    monkeypatch.setenv("MEMORYOPS_AUTH_MODE", "trusted_header")
    monkeypatch.setenv("MEMORYOPS_STORAGE", "memory")
    _clear()
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    # Two users in one tenant, each with their own audit trail.
    client.post(
        "/api/chat",
        json={
            "tenant_id": "acme",
            "user_id": "alice",
            "message": "Remember: alice likes dark mode.",
        },
        headers=_hdr("alice"),
    )
    client.post(
        "/api/chat",
        json={
            "tenant_id": "acme",
            "user_id": "bob",
            "message": "Remember: bob likes light mode.",
        },
        headers=_hdr("bob"),
    )
    yield client
    _clear()


def test_tenant_wide_audit_is_refused_without_the_permission(rbac_client):
    """The exact reproduction: omitting `user_id` used to return everyone's rows."""
    r = rbac_client.get("/api/audit?tenant_id=acme", headers=_hdr("alice"))
    assert r.status_code == 403
    assert "audit:read:tenant" in r.json()["detail"]


def test_auditor_may_read_tenant_wide_audit(rbac_client):
    r = rbac_client.get("/api/audit?tenant_id=acme", headers=_hdr("alice", "auditor"))
    assert r.status_code == 200
    assert {e["user_id"] for e in r.json()} >= {"alice", "bob"}


def test_tenant_admin_may_read_tenant_wide_audit(rbac_client):
    r = rbac_client.get("/api/audit?tenant_id=acme", headers=_hdr("alice", "tenant_admin"))
    assert r.status_code == 200


def test_a_user_cannot_read_another_users_audit(rbac_client):
    r = rbac_client.get("/api/audit?tenant_id=acme&user_id=bob", headers=_hdr("alice"))
    assert r.status_code == 403


def test_a_user_can_read_their_own_audit(rbac_client):
    r = rbac_client.get("/api/audit?tenant_id=acme&user_id=alice", headers=_hdr("alice"))
    assert r.status_code == 200
    assert {e["user_id"] for e in r.json()} <= {"alice"}


def test_cross_tenant_audit_is_refused_even_for_an_admin(rbac_client):
    """A tenant_admin of acme is not an admin of evilcorp."""
    r = rbac_client.get(
        "/api/audit?tenant_id=evilcorp", headers=_hdr("alice", "tenant_admin")
    )
    assert r.status_code == 403
    body = str(r.json())
    assert "evilcorp" not in body or "scope" in body


# ── metrics ──────────────────────────────────────────────────────────────────
def test_tenant_metrics_require_the_permission(rbac_client):
    denied = rbac_client.get("/api/metrics?tenant_id=acme", headers=_hdr("alice"))
    assert denied.status_code == 403
    ok = rbac_client.get("/api/metrics?tenant_id=acme", headers=_hdr("alice", "auditor"))
    assert ok.status_code == 200


# ── worker health ────────────────────────────────────────────────────────────
def test_public_worker_health_never_exposes_tenant_or_user_identifiers(rbac_client):
    """`last_run_per_scope` keys are `f"{tenant_id}:{user_id}"`, and this endpoint
    sits outside the `/api/*` auth boundary — so it was leaking every scope the
    fleet had processed to any unauthenticated caller."""
    r = rbac_client.get("/healthz/workers")
    assert r.status_code == 200
    body = r.json()
    assert "last_run_per_scope" not in body
    blob = str(body)
    for identifier in ("acme", "alice", "bob", ":"):
        if identifier == ":":
            continue
        assert identifier not in blob, f"public worker health leaked {identifier!r}"


def test_detailed_worker_health_requires_worker_read(rbac_client):
    reader = rbac_client.get("/api/admin/workers/health", headers=_hdr("alice"))
    assert reader.status_code == 403
    assert (
        rbac_client.get(
            "/api/admin/workers/health", headers=_hdr("svc", "service_worker")
        ).status_code
        == 200
    )
    assert (
        rbac_client.get(
            "/api/admin/workers/health", headers=_hdr("alice", "tenant_admin")
        ).status_code
        == 200
    )


def test_detailed_worker_health_is_inside_the_auth_boundary(rbac_client):
    """Unauthenticated access must be rejected, not merely unauthorized."""
    r = rbac_client.get("/api/admin/workers/health")
    assert r.status_code in (401, 403)


# ── auth disabled keeps the demo working ─────────────────────────────────────
def test_authorization_is_a_no_op_when_auth_is_disabled(api_client):
    """Same contract as `enforce_scope`: no principal, no enforcement.

    Safe because `MEMORYOPS_PROFILE=production` refuses to start with
    `auth_mode=none` (see tests/test_production_profile.py).
    """
    client, _repo = api_client
    assert client.get("/api/audit?tenant_id=t1").status_code == 200
    assert client.get("/api/metrics?tenant_id=t1").status_code == 200
