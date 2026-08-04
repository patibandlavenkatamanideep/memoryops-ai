"""Machine-readable authorization contract for every route.

Why this exists before any handler changes
------------------------------------------
The endpoint authorization matrix was maintained by hand, and it drifted: it listed
chat, memories, retention, consent, traces, evidence and evals as
permission-protected while only audit, tenant metrics and detailed worker health
actually checked anything. Documentation ahead of runtime is the failure mode this
project keeps closing, so the matrix is now *generated* from these declarations.

Declaring a contract is not the same as enforcing it. Every route is classified
immediately — that is what makes the enumeration guard meaningful — but a route
carries ``status=PLANNED`` until its handler genuinely checks the permission. The
generated matrix renders Enforced, Planned and Public separately, so it can never
again claim a control that does not run.

Why a registry rather than route decorators
-------------------------------------------
`Depends(...)` markers are only discoverable if every route remembers to add one,
which is the drift being eliminated. A central registry keyed by (method, path) can
be diffed against the *actual* router table, so a route that exists but was never
classified is a hard CI failure rather than a silent omission.

A note on enumerating routes
----------------------------
`app.routes` is not a flat list. This FastAPI version wraps `include_router` results
in `_IncludedRouter` objects, so a naive walk finds four paths and **zero** API
routes — a guard written that way would pass vacuously while checking nothing.
`iter_routes` descends deliberately, and a test asserts it discovers the real API
surface.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum

from .roles import Permission


class Scope(str, Enum):
    """How a route decides who may call it."""

    #: Unauthenticated by design. Must expose no tenant or user identifiers.
    PUBLIC = "public"
    #: Any authenticated principal; no specific permission.
    AUTHENTICATED = "authenticated"
    #: Acts on the caller's own records only.
    SELF = "self"
    #: Acts across the tenant.
    TENANT = "tenant"
    #: Ownership is decided from the *loaded resource*, then self- or
    #: tenant-permission applies. Never from a tenant/user supplied in the body.
    RESOURCE = "resource"
    #: Operator/machine surface (worker health, replay).
    OPERATOR = "operator"


class Status(str, Enum):
    ENFORCED = "enforced"
    #: Classified, contract agreed, handler does not check it yet.
    PLANNED = "planned"
    PUBLIC = "public"


@dataclass(frozen=True)
class AuthzSpec:
    """The authorization contract for one (method, path)."""

    scope: Scope
    status: Status
    #: Required for SELF / TENANT / OPERATOR scopes.
    permission: Permission | None = None
    #: Required for RESOURCE scope — which permission applies depends on whether the
    #: loaded record belongs to the caller.
    self_permission: Permission | None = None
    tenant_permission: Permission | None = None
    note: str = ""

    @property
    def is_mutation_scope(self) -> bool:
        return self.scope in (Scope.SELF, Scope.TENANT, Scope.RESOURCE, Scope.OPERATOR)

    def permissions(self) -> tuple[Permission, ...]:
        found = [self.permission, self.self_permission, self.tenant_permission]
        return tuple(p for p in found if p is not None)


_P = Permission
_S = Scope
_ST = Status

#: (METHOD, path) -> contract. Paths are the FastAPI templates, e.g.
#: "/api/memories/{memory_id}". Every route in the app must appear here.
ROUTE_AUTHZ: dict[tuple[str, str], AuthzSpec] = {
    # ── public ──────────────────────────────────────────────────────────────
    ("GET", "/"): AuthzSpec(_S.PUBLIC, _ST.PUBLIC, note="service banner"),
    ("GET", "/healthz"): AuthzSpec(_S.PUBLIC, _ST.PUBLIC, note="process liveness"),
    ("GET", "/healthz/workers"): AuthzSpec(
        _S.PUBLIC, _ST.PUBLIC, note="boolean health only; no counts, no scope keys"
    ),
    ("GET", "/readyz"): AuthzSpec(
        _S.PUBLIC,
        _ST.PUBLIC,
        note=(
            "dependency states with reason codes, no secrets. Candidate for "
            "restriction: it discloses which providers and backends are configured."
        ),
    ),
    ("GET", "/metrics"): AuthzSpec(
        _S.PUBLIC,
        _ST.PUBLIC,
        note=(
            "Prometheus exposition, content-free and low-cardinality (no tenant or "
            "user labels). Should be private-network-only or operator-gated; it sits "
            "outside the /api/* auth boundary today."
        ),
    ),
    ("GET", "/docs"): AuthzSpec(_S.PUBLIC, _ST.PUBLIC, note="deployment-configurable"),
    ("GET", "/docs/oauth2-redirect"): AuthzSpec(_S.PUBLIC, _ST.PUBLIC),
    ("GET", "/redoc"): AuthzSpec(_S.PUBLIC, _ST.PUBLIC, note="deployment-configurable"),
    ("GET", "/openapi.json"): AuthzSpec(
        _S.PUBLIC, _ST.PUBLIC, note="deployment-configurable; describes the full surface"
    ),
    # ── memory lifecycle ────────────────────────────────────────────────────
    ("POST", "/api/chat"): AuthzSpec(
        _S.SELF, _ST.PLANNED, permission=_P.MEMORY_WRITE_SELF, note="chat writes memory"
    ),
    ("GET", "/api/memories"): AuthzSpec(
        _S.RESOURCE,
        _ST.PLANNED,
        self_permission=_P.MEMORY_READ_SELF,
        tenant_permission=_P.MEMORY_READ_TENANT,
    ),
    ("GET", "/api/memories/{memory_id}"): AuthzSpec(
        _S.RESOURCE,
        _ST.PLANNED,
        self_permission=_P.MEMORY_READ_SELF,
        tenant_permission=_P.MEMORY_READ_TENANT,
    ),
    ("PATCH", "/api/memories/{memory_id}"): AuthzSpec(
        _S.RESOURCE,
        _ST.PLANNED,
        self_permission=_P.MEMORY_WRITE_SELF,
        tenant_permission=_P.MEMORY_WRITE_TENANT,
        note=(
            "content/metadata edits. Status transitions carry their own permissions: "
            "approve/reject are tenant-only even for the caller's own record; "
            "archive/restore follow memory:archive:*. Legal hold and the revision "
            "check still apply — authorization does not bypass them."
        ),
    ),
    ("DELETE", "/api/memories/{memory_id}"): AuthzSpec(
        _S.RESOURCE,
        _ST.PLANNED,
        self_permission=_P.MEMORY_DELETE_SELF,
        tenant_permission=_P.MEMORY_DELETE_TENANT,
        note="a user may delete their own pending memory; legal hold still overrides",
    ),
    ("GET", "/api/memories/{memory_id}/audit"): AuthzSpec(
        _S.RESOURCE,
        _ST.PLANNED,
        self_permission=_P.AUDIT_READ_SELF,
        tenant_permission=_P.AUDIT_READ_TENANT,
    ),
    ("GET", "/api/memories/{memory_id}/provenance"): AuthzSpec(
        _S.RESOURCE,
        _ST.PLANNED,
        self_permission=_P.MEMORY_READ_SELF,
        tenant_permission=_P.MEMORY_READ_TENANT,
    ),
    # ── governance + evidence ───────────────────────────────────────────────
    ("GET", "/api/audit"): AuthzSpec(
        _S.RESOURCE,
        _ST.ENFORCED,
        self_permission=_P.AUDIT_READ_SELF,
        tenant_permission=_P.AUDIT_READ_TENANT,
        note="tenant-wide requires audit:read:tenant; otherwise forced to own user",
    ),
    ("GET", "/api/metrics"): AuthzSpec(
        _S.TENANT, _ST.ENFORCED, permission=_P.METRICS_READ_TENANT
    ),
    ("GET", "/api/traces"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.TRACES_READ_TENANT
    ),
    ("GET", "/api/evidence/response/{trace_id}"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.EVIDENCE_READ
    ),
    ("GET", "/api/evidence/deletion/{memory_id}"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.EVIDENCE_READ
    ),
    ("GET", "/api/evidence/lifecycle/{memory_id}"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.EVIDENCE_READ
    ),
    ("GET", "/api/evidence/policy"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.EVIDENCE_READ
    ),
    ("GET", "/api/evidence/audit/verify"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.EVIDENCE_READ
    ),
    # Retention: reads and mutations are deliberately separate permissions rather
    # than one blanket grant on the router.
    ("GET", "/api/retention/policies"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.RETENTION_READ
    ),
    ("GET", "/api/retention/decisions"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.RETENTION_READ
    ),
    ("GET", "/api/retention/memory/{memory_id}"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.RETENTION_READ
    ),
    ("POST", "/api/retention/legal-hold"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.RETENTION_MANAGE
    ),
    ("POST", "/api/retention/pin"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.RETENTION_MANAGE
    ),
    ("POST", "/api/retention/protect"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.RETENTION_MANAGE
    ),
    ("POST", "/api/retention/consent"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.CONSENT_MANAGE
    ),
    # ── loops (operational timelines, tenant-scoped) ────────────────────────
    ("GET", "/api/loops"): AuthzSpec(
        _S.AUTHENTICATED, _ST.PLANNED, note="static loop definitions; no tenant data"
    ),
    ("GET", "/api/loops/{loop_id}"): AuthzSpec(
        _S.AUTHENTICATED, _ST.PLANNED, note="static loop definition"
    ),
    ("GET", "/api/loops/runs"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.TRACES_READ_TENANT
    ),
    ("GET", "/api/loops/events"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.TRACES_READ_TENANT
    ),
    ("GET", "/api/loops/trace/{trace_id}"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.TRACES_READ_TENANT
    ),
    # ── evals (cost-bearing) ────────────────────────────────────────────────
    ("POST", "/api/evals/run"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.EVALS_RUN, note="denial-of-wallet vector"
    ),
    ("GET", "/api/evals/latest"): AuthzSpec(
        _S.TENANT, _ST.PLANNED, permission=_P.EVALS_RUN
    ),
    # ── operator ────────────────────────────────────────────────────────────
    ("GET", "/api/admin/workers/health"): AuthzSpec(
        _S.OPERATOR, _ST.ENFORCED, permission=_P.WORKER_READ
    ),
}


def iter_routes(app) -> Iterator[tuple[str, str]]:
    """Yield every (METHOD, path) the application actually serves.

    Descends into included routers. `app.routes` is not flat in this FastAPI
    version — `include_router` results are wrapped in `_IncludedRouter` objects, so
    a naive walk finds four paths and no API routes at all. A guard built on that
    would pass while checking nothing.
    """

    def walk(routes) -> Iterator[tuple[str, str]]:
        for route in routes:
            included = getattr(route, "original_router", None)
            if included is not None:
                yield from walk(getattr(included, "routes", []))
                continue
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if not path or not methods:
                continue
            for method in sorted(methods):
                if method in ("HEAD", "OPTIONS"):
                    continue
                yield (method, path)

    seen: set[tuple[str, str]] = set()
    for entry in walk(app.routes):
        if entry not in seen:
            seen.add(entry)
            yield entry
