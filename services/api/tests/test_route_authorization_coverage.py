"""Every route must declare an authorization contract.

The endpoint authorization matrix was maintained by hand and drifted: it listed
chat, memories, retention, consent, traces, evidence and evals as
permission-protected while only audit, tenant metrics and detailed worker health
actually checked anything.

This makes the matrix executable. A route that exists but was never classified is a
CI failure, so the documented surface cannot get ahead of the runtime again.

Declaring is not enforcing. A route carries `status=PLANNED` until its handler
genuinely checks the permission, and the generated matrix renders Enforced, Planned
and Public separately. These tests police the *classification*; later commits move
routes from planned to enforced.
"""

from __future__ import annotations

import pytest

from app.auth.authz_spec import ROUTE_AUTHZ, AuthzSpec, Scope, Status, iter_routes
from app.auth.roles import Permission, Role, permissions_for


@pytest.fixture(scope="module")
def routes():
    from app.main import app

    return sorted(iter_routes(app))


# ── the guard must not pass vacuously ────────────────────────────────────────
def test_route_discovery_finds_the_real_api_surface(routes):
    """`app.routes` is not flat in this FastAPI version — `include_router` results
    are wrapped in `_IncludedRouter`, so a naive walk finds four paths and **zero**
    API routes. A guard written that way would pass while checking nothing.
    """
    assert len(routes) > 30, f"only discovered {len(routes)} routes — walker is broken"
    paths = {path for _method, path in routes}
    for expected in (
        "/api/chat",
        "/api/memories",
        "/api/memories/{memory_id}",
        "/api/audit",
        "/api/retention/legal-hold",
        "/api/evidence/policy",
        "/api/admin/workers/health",
        "/healthz",
        "/metrics",
        "/readyz",
    ):
        assert expected in paths, f"route discovery missed {expected}"


# ── classification completeness ──────────────────────────────────────────────
def test_every_route_declares_an_authorization_contract(routes):
    unclassified = [f"{m} {p}" for m, p in routes if (m, p) not in ROUTE_AUTHZ]
    assert not unclassified, (
        "these routes have no AuthzSpec — add one to ROUTE_AUTHZ:\n  "
        + "\n  ".join(unclassified)
    )


def test_no_stale_declarations(routes):
    """A contract for a route that no longer exists is drift in the other direction."""
    actual = set(routes)
    stale = [f"{m} {p}" for (m, p) in ROUTE_AUTHZ if (m, p) not in actual]
    assert not stale, "ROUTE_AUTHZ declares routes the app does not serve:\n  " + "\n  ".join(stale)


# ── contract shape rules ─────────────────────────────────────────────────────
def test_admin_routes_always_require_an_explicit_permission(routes):
    for method, path in routes:
        if not path.startswith("/api/admin/"):
            continue
        spec = ROUTE_AUTHZ[(method, path)]
        assert spec.scope is not Scope.PUBLIC, f"{path} is an admin route and cannot be public"
        assert spec.permissions(), f"{path} declares no permission"


def test_mutations_declare_an_action_permission(routes):
    """A POST/PATCH/DELETE with no permission is a hole, not a default."""
    for method, path in routes:
        if method not in ("POST", "PATCH", "PUT", "DELETE"):
            continue
        spec = ROUTE_AUTHZ[(method, path)]
        assert spec.scope is not Scope.PUBLIC, f"{method} {path} must not be public"
        assert spec.permissions(), f"{method} {path} declares no action permission"


def test_tenant_scoped_routes_declare_a_tenant_permission(routes):
    for method, path in routes:
        spec = ROUTE_AUTHZ[(method, path)]
        if spec.scope is not Scope.TENANT:
            continue
        assert spec.permission is not None, f"{method} {path} is tenant-scoped with no permission"


def test_resource_scoped_routes_declare_both_permissions(routes):
    """Resource scope exists precisely because self and tenant differ."""
    for method, path in routes:
        spec = ROUTE_AUTHZ[(method, path)]
        if spec.scope is not Scope.RESOURCE:
            continue
        assert spec.self_permission is not None, f"{method} {path} lacks a self permission"
        assert spec.tenant_permission is not None, f"{method} {path} lacks a tenant permission"


def test_public_routes_are_a_short_explicit_list(routes):
    """Public is the exception. Keep it small enough to review by eye."""
    public = sorted(p for (m, p) in routes if ROUTE_AUTHZ[(m, p)].scope is Scope.PUBLIC)
    assert public == [
        "/",
        "/docs",
        "/docs/oauth2-redirect",
        "/healthz",
        "/healthz/workers",
        "/metrics",
        "/openapi.json",
        "/readyz",
        "/redoc",
    ], f"the public surface changed: {public}"


def test_no_api_route_is_public_except_none(routes):
    """Nothing under /api/ may be public — including future additions."""
    leaked = [
        f"{m} {p}"
        for m, p in routes
        if p.startswith("/api/") and ROUTE_AUTHZ[(m, p)].scope is Scope.PUBLIC
    ]
    assert not leaked, f"/api routes classified public: {leaked}"


# ── permissions referenced must exist and be reachable ───────────────────────
def test_every_declared_permission_is_held_by_some_role():
    """A permission no role grants is unreachable — the route would be dead."""
    grantable = set()
    for role in Role:
        grantable |= permissions_for(frozenset({role}))
    for (method, path), spec in ROUTE_AUTHZ.items():
        for permission in spec.permissions():
            assert permission in grantable, (
                f"{method} {path} requires {permission.value}, which no role grants"
            )


def test_declared_permissions_are_real_permission_values():
    for spec in ROUTE_AUTHZ.values():
        for permission in spec.permissions():
            assert isinstance(permission, Permission)


# ── status honesty ───────────────────────────────────────────────────────────
def test_public_scope_and_public_status_agree():
    for (method, path), spec in ROUTE_AUTHZ.items():
        if spec.scope is Scope.PUBLIC:
            assert spec.status is Status.PUBLIC, f"{method} {path} scope/status disagree"
        else:
            assert spec.status is not Status.PUBLIC, f"{method} {path} scope/status disagree"


def test_the_currently_enforced_set_is_exactly_what_ships():
    """Pins reality. Moving a route to ENFORCED requires changing this list, which
    forces the claim and the handler to change together."""
    enforced = sorted(
        f"{m} {p}" for (m, p), spec in ROUTE_AUTHZ.items() if spec.status is Status.ENFORCED
    )
    assert enforced == [
        "GET /api/admin/workers/health",
        "GET /api/audit",
        "GET /api/metrics",
    ], f"enforced set changed: {enforced}"


def test_a_planned_route_is_not_described_as_enforced():
    planned = [spec for spec in ROUTE_AUTHZ.values() if spec.status is Status.PLANNED]
    assert planned, "nothing planned — did the registry lose its remaining work?"
    for spec in planned:
        if spec.scope is Scope.AUTHENTICATED:
            # "any authenticated principal" is the contract; there is no narrower
            # permission to name.
            continue
        assert spec.permissions(), "a planned route must still name its intended permission"


# ── the guard has teeth ──────────────────────────────────────────────────────
def test_an_unclassified_route_is_detected(routes):
    """Simulates adding a route without a contract."""
    actual = set(routes) | {("GET", "/api/admin/export")}
    unclassified = [f"{m} {p}" for m, p in actual if (m, p) not in ROUTE_AUTHZ]
    assert unclassified == ["GET /api/admin/export"]


def test_an_admin_route_without_a_permission_is_detected():
    rogue = AuthzSpec(Scope.OPERATOR, Status.PLANNED)
    assert not rogue.permissions()


def test_the_generated_matrix_matches_the_route_contracts():
    """The documented matrix is derived from ROUTE_AUTHZ, not maintained by hand."""
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path

    repo_root = _Path(__file__).resolve().parents[3]
    proc = subprocess.run(
        [_sys.executable, str(repo_root / "scripts" / "generate_authz_matrix.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"authorization matrix drift:\n{proc.stdout}\n{proc.stderr}\n"
        "Run: python scripts/generate_authz_matrix.py"
    )
