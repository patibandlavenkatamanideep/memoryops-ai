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


# ── three-state role resolution ──────────────────────────────────────────────
def test_a_role_claim_naming_nothing_recognised_grants_nothing():
    """A typo must not hand out permissions.

    Collapsing "no claim" and "claim present but invalid" into `memory_reader`
    would give `roles=["service_workre"]` both `memory:read:self` and
    `memory:write:self` — human memory access for a credential that was meant to be
    an operational service account.
    """
    from app.auth.principal import Principal
    from app.auth.roles import resolve_roles

    roles, present = resolve_roles(["service_workre"])
    assert roles == frozenset()
    assert present is True

    p = Principal(
        tenant_id="t", user_id="u", provider="jwt",
        roles=roles, role_claim_present=present,
    )
    assert p.effective_roles == frozenset()
    assert p.permissions == frozenset()
    assert not p.has(Permission.MEMORY_READ_SELF)


# NOTE: an earlier two-state version of this test asserted that "" and [] were
# *absent*. That is the behaviour this change corrects, so it is superseded by
# `test_presence_distinguishes_all_four_states` below rather than kept alongside it.


def test_a_missing_claim_can_be_required_instead_of_defaulted():
    from app.auth.principal import Principal

    lenient = Principal(tenant_id="t", user_id="u", provider="jwt")
    assert lenient.effective_roles == frozenset({DEFAULT_ROLE})

    strict = Principal(tenant_id="t", user_id="u", provider="jwt", require_role_claim=True)
    assert strict.effective_roles == frozenset()
    assert strict.permissions == frozenset()


def test_production_requires_an_explicit_role_claim():
    from app.core.config import Settings

    hardened = dict(
        profile="production",
        storage="postgres",
        auth_mode="jwt",
        cors_allow_origins="https://app.example.com",
        database_url="postgresql+psycopg://real:secret@db.internal:5432/memoryops",
        public_evals=False,
    )
    errors = Settings(**hardened).production_readiness_errors()
    assert any("auth_require_role_claim" in e for e in errors)
    assert Settings(**hardened, auth_require_role_claim=True).production_readiness_errors() == []


# ── service account identity is explicit, never inferred ─────────────────────
def test_service_account_comes_from_a_verified_claim_not_a_role_name():
    """`is_service_account` was declared but never populated. Inferring it from the
    role name would make the contract implicit and unverifiable."""
    from app.auth.providers import TrustedHeaderProvider

    provider = TrustedHeaderProvider(
        "X-MemoryOps-Tenant", "X-MemoryOps-User",
        "X-MemoryOps-Roles", "X-MemoryOps-Actor-Type",
    )
    human = provider.resolve(
        {"x-memoryops-tenant": "t", "x-memoryops-user": "u", "x-memoryops-roles": "service_worker"}
    )
    assert human is not None and human.is_service_account is False

    machine = provider.resolve(
        {
            "x-memoryops-tenant": "t",
            "x-memoryops-user": "svc",
            "x-memoryops-roles": "service_worker",
            "x-memoryops-actor-type": "service_account",
        }
    )
    assert machine is not None and machine.is_service_account is True


# ── public worker health is liveness only ────────────────────────────────────
def test_public_worker_health_exposes_no_activity_counts(rbac_client):
    """Aggregate run and failure counts still disclose deployment activity and
    operational condition to an unauthenticated caller."""
    body = rbac_client.get("/healthz/workers").json()
    assert set(body.keys()) == {"healthy"}
    for leaked in ("runs_observed", "dead_letter_count", "failed_count", "last_run_per_scope"):
        assert leaked not in body


# ── auth disabled keeps the demo working ─────────────────────────────────────
def test_authorization_is_a_no_op_when_auth_is_disabled(api_client):
    """Same contract as `enforce_scope`: no principal, no enforcement.

    Safe because `MEMORYOPS_PROFILE=production` refuses to start with
    `auth_mode=none` (see tests/test_production_profile.py).
    """
    client, _repo = api_client
    assert client.get("/api/audit?tenant_id=t1").status_code == 200
    assert client.get("/api/metrics?tenant_id=t1").status_code == 200


# ── an explicitly empty role claim is a decision, not an absence ─────────────
# Presence was `raw is not None and raw != "" and raw != []`, so an issuer that
# deliberately granted a credential *no roles* was indistinguishable from an older
# credential that predates roles entirely. The empty set silently received the
# `memory_reader` fallback — memory:read:self and memory:write:self for an identity
# the issuer said should have nothing.
def _principal(raw):
    from app.auth.principal import Principal
    from app.auth.roles import resolve_roles

    roles, present = resolve_roles(raw)
    return Principal(
        tenant_id="t", user_id="u", provider="jwt",
        roles=roles, role_claim_present=present,
    )


@pytest.mark.parametrize("empty", [[], "", (), frozenset()])
def test_an_explicitly_empty_role_claim_grants_nothing(empty):
    p = _principal(empty)
    assert p.effective_roles == frozenset()
    assert p.permissions == frozenset()
    assert not p.has(Permission.MEMORY_READ_SELF)
    assert not p.has(Permission.MEMORY_WRITE_SELF)


def test_an_omitted_claim_still_falls_back_where_permitted():
    """Omission is a compatibility question the deployment answers; emptiness is an
    authorization decision the issuer already made."""
    p = _principal(None)
    assert p.effective_roles == frozenset({DEFAULT_ROLE})
    assert p.has(Permission.MEMORY_READ_SELF)


def test_presence_distinguishes_all_four_states():
    from app.auth.roles import resolve_roles

    assert resolve_roles(None) == (frozenset(), False)          # omitted
    assert resolve_roles([]) == (frozenset(), True)             # present, empty
    assert resolve_roles("") == (frozenset(), True)             # present, empty
    assert resolve_roles("auditor") == (frozenset({Role.AUDITOR}), True)
    assert resolve_roles("nonsense") == (frozenset(), True)     # present, invalid


def test_a_trusted_header_present_but_empty_grants_nothing():
    from app.auth.providers import TrustedHeaderProvider

    provider = TrustedHeaderProvider(
        "X-MemoryOps-Tenant", "X-MemoryOps-User", "X-MemoryOps-Roles"
    )
    absent = provider.resolve({"x-memoryops-tenant": "t", "x-memoryops-user": "u"})
    assert absent is not None and absent.effective_roles == frozenset({DEFAULT_ROLE})

    empty = provider.resolve(
        {"x-memoryops-tenant": "t", "x-memoryops-user": "u", "x-memoryops-roles": ""}
    )
    assert empty is not None
    assert empty.role_claim_present is True
    assert empty.permissions == frozenset()


def test_a_production_credential_without_roles_gets_nothing():
    p = _principal(None)
    strict = type(p)(
        tenant_id="t", user_id="u", provider="jwt",
        roles=p.roles, role_claim_present=p.role_claim_present,
        require_role_claim=True,
    )
    assert strict.permissions == frozenset()
