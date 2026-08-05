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

from ._authz_domains import is_governance_domain, is_memory_domain


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


def test_ownership_scoped_routes_declare_both_permissions(routes):
    """RESOURCE and SUBJECT exist precisely because self and tenant differ.

    Two valid shapes:
      * without variants — a top-level self/tenant pair decides the route;
      * with variants — each action decides itself, and the top-level pair must be
        ABSENT so there is no second authorization path a handler could take
        instead, silently skipping archive/approve/reject.
    """
    for method, path in routes:
        spec = ROUTE_AUTHZ[(method, path)]
        if spec.scope not in (Scope.RESOURCE, Scope.SUBJECT):
            continue
        if spec.is_variant_driven:
            assert spec.self_permission is None and spec.tenant_permission is None, (
                f"{method} {path} declares variants *and* a generic fallback pair — "
                "remove the fallback so the safe path is the only representable one"
            )
            for variant in spec.variants:
                assert variant.permissions(), (
                    f"{method} {path} variant '{variant.action}' names no permission"
                )
            continue
        assert spec.self_permission is not None, f"{method} {path} lacks a self permission"
        assert spec.tenant_permission is not None, f"{method} {path} lacks a tenant permission"


def test_subject_and_resource_scopes_are_assigned_deliberately(routes):
    """RESOURCE means a stored record is loaded before ownership is decided.
    SUBJECT means a requested user is resolved before querying.

    /api/audit was RESOURCE while resolving an optional `user_id` — contradicting
    the registry's own definition, and it would have modelled the first real
    subject-scope helper as a special case.
    """
    subject = {p for (m, p) in routes if ROUTE_AUTHZ[(m, p)].scope is Scope.SUBJECT}
    assert "/api/audit" in subject
    assert "/api/memories" in subject

    resource = {p for (m, p) in routes if ROUTE_AUTHZ[(m, p)].scope is Scope.RESOURCE}
    for path in resource:
        assert "{" in path, (
            f"{path} is RESOURCE-scoped but takes no identifier — a route with no "
            "record to load cannot decide ownership from one"
        )


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
        "DELETE /api/memories/{memory_id}",
        "GET /api/admin/workers/health",
        "GET /api/audit",
        "GET /api/evals/latest",
        "GET /api/evidence/audit/verify",
        "GET /api/evidence/deletion/{memory_id}",
        "GET /api/evidence/lifecycle/{memory_id}",
        "GET /api/evidence/policy",
        "GET /api/evidence/response/{trace_id}",
        "GET /api/loops",
        "GET /api/loops/events",
        "GET /api/loops/runs",
        "GET /api/loops/trace/{trace_id}",
        "GET /api/loops/{loop_id}",
        "GET /api/memories",
        "GET /api/memories/{memory_id}",
        "GET /api/memories/{memory_id}/audit",
        "GET /api/memories/{memory_id}/provenance",
        "GET /api/metrics",
        "GET /api/retention/decisions",
        "GET /api/retention/memory/{memory_id}",
        "GET /api/retention/policies",
        "GET /api/traces",
        "PATCH /api/memories/{memory_id}",
        "POST /api/chat",
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


# ── duplicate registrations ──────────────────────────────────────────────────
def test_no_duplicate_method_path_registrations():
    """`iter_routes` deduplicates, which would hide a real defect.

    Registering `GET /api/example` twice emits one deduplicated entry, matches one
    contract, and passes every check above — while the app has two handlers whose
    precedence depends on registration order. The raw iterator exists so this can
    fail.
    """
    from collections import Counter

    from app.auth.authz_spec import iter_routes_raw
    from app.main import app

    counts = Counter(iter_routes_raw(app))
    duplicates = {f"{m} {p}": n for (m, p), n in counts.items() if n > 1}
    assert not duplicates, f"routes registered more than once: {duplicates}"


# ── enforcement witness ──────────────────────────────────────────────────────
# The pinned ENFORCED set stops a route being *described* as enforced by accident.
# It cannot stop: flip PLANNED -> ENFORCED, update the pinned list, forget to call
# the helper. A pinned list is a claim about code; the witness is evidence from it.
# The reject/permit cases for these three routes live in test_api_rbac.py, which
# owns the authenticated client fixture. Here we prove the *helper ran*, which those
# tests cannot show: a handler that silently stopped checking could still return 200
# for an authorized caller and 403 for no one.
def test_the_helpers_record_a_witness_for_every_enforced_route():
    """Directly exercises the helpers so the recorded route/permission can be read.

    Going through the TestClient would discard `request.state` before the assertion,
    so this drives the same code path with a stub request.
    """
    from types import SimpleNamespace

    from app.auth.dependencies import require_permission
    from app.auth.principal import Principal
    from app.auth.roles import Role
    from app.auth.witness import witness_for

    class _Route:
        path = "/api/admin/workers/health"

    principal = Principal(
        tenant_id="acme",
        user_id="svc",
        provider="trusted_header",
        roles=frozenset({Role.SERVICE_WORKER}),
        role_claim_present=True,
    )
    request = SimpleNamespace(
        method="GET",
        state=SimpleNamespace(principal=principal),
        scope={"route": _Route()},
    )

    require_permission(request, Permission.WORKER_READ)

    recorded = witness_for(request)
    assert recorded, "no authorization decision was recorded"
    decision = recorded.for_route("GET", "/api/admin/workers/health")[0]
    assert decision.helper == "require_permission"
    assert decision.permission is Permission.WORKER_READ


#: Enforced routes whose witness is asserted in this module, by driving the helper
#: directly. The memory and governance domains are covered instead by their runtime
#: gates (`test_memory_route_authorization.py`, `test_governance_read_authorization.py`),
#: which drive the **real route** through the app and read the witness back off the
#: request — a stronger check than a name in a list, because it fails when a handler
#: stops calling the helper. Domain membership is shared via `_authz_domains` so the
#: gates and this guard cannot disagree about who covers what.
_WITNESSED_HERE = frozenset(
    {
        "GET /api/audit",
        "GET /api/metrics",
        "GET /api/admin/workers/health",
    }
)


def test_every_enforced_route_has_a_witness_test():
    """A route may not be marked ENFORCED without evidence that a check runs.

    Two lists agreeing proves only that someone updated both. The memory routes are
    therefore held to the runtime gate in `test_memory_route_authorization.py`; this
    guard exists to catch an enforced route that belongs to *neither* set, which is
    the case that would otherwise pass silently.
    """
    enforced = {
        f"{m} {p}" for (m, p), spec in ROUTE_AUTHZ.items() if spec.status is Status.ENFORCED
    }
    runtime_gated = {
        f"{m} {p}"
        for (m, p), spec in ROUTE_AUTHZ.items()
        if spec.status is Status.ENFORCED
        and (is_memory_domain(p) or is_governance_domain(p))
    }
    uncovered = enforced - _WITNESSED_HERE - runtime_gated
    assert not uncovered, (
        "an ENFORCED route has no witness test — add one before flipping its status: "
        f"{sorted(uncovered)}"
    )
    stale = _WITNESSED_HERE - enforced
    assert not stale, f"witness list names routes that are no longer enforced: {sorted(stale)}"
