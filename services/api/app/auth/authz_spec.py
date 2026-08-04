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
    #: A collection query whose *subject* is requested rather than loaded. There is
    #: no stored record to inspect ownership on, so the helper resolves the
    #: requested subject against the principal and then **forces** the repository
    #: query to the authorized subject. Validating a supplied `user_id` and then
    #: continuing to use the untrusted value would not be authorization.
    SUBJECT = "subject"
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
class AuthzVariant:
    """One action a route can perform, when a single method/path has several.

    `PATCH /api/memories/{id}` is an edit, an archive, a restore, an approval or a
    rejection depending on the validated transition — and those carry different
    permissions. A path-and-method-only contract cannot express that, which matters
    for the API, the generated matrix, and the web capability artifact that has to
    decide whether a persona may approve as opposed to edit.

    The action is derived from the *validated transition*, never from a
    client-supplied action string.
    """

    action: str
    self_permission: Permission | None = None
    tenant_permission: Permission | None = None
    note: str = ""

    def permissions(self) -> tuple[Permission, ...]:
        found = [self.self_permission, self.tenant_permission]
        return tuple(p for p in found if p is not None)


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
    #: Set when one method/path performs several distinct actions.
    variants: tuple[AuthzVariant, ...] = ()
    note: str = ""

    def variant(self, action: str) -> AuthzVariant | None:
        for candidate in self.variants:
            if candidate.action == action:
                return candidate
        return None

    @property
    def is_mutation_scope(self) -> bool:
        return self.scope in (Scope.SELF, Scope.TENANT, Scope.RESOURCE, Scope.OPERATOR)

    def permissions(self) -> tuple[Permission, ...]:
        found = [self.permission, self.self_permission, self.tenant_permission]
        for variant in self.variants:
            found.extend(variant.permissions())
        seen: list[Permission] = []
        for permission in found:
            if permission is not None and permission not in seen:
                seen.append(permission)
        return tuple(seen)


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
        # Collection query: no stored record exists to inspect ownership on, so the
        # helper resolves the requested subject and forces the query to it.
        _S.SUBJECT,
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
        variants=(
            AuthzVariant(
                "edit",
                self_permission=_P.MEMORY_WRITE_SELF,
                tenant_permission=_P.MEMORY_WRITE_TENANT,
                note="content, importance, confidence",
            ),
            AuthzVariant(
                "archive",
                self_permission=_P.MEMORY_ARCHIVE_SELF,
                tenant_permission=_P.MEMORY_ARCHIVE_TENANT,
            ),
            AuthzVariant(
                "restore",
                self_permission=_P.MEMORY_ARCHIVE_SELF,
                tenant_permission=_P.MEMORY_ARCHIVE_TENANT,
                note="archived -> active is the same lifecycle control as archiving",
            ),
            AuthzVariant(
                "approve",
                tenant_permission=_P.MEMORY_APPROVE_TENANT,
                note="tenant-only even for the caller's own record — self-approval "
                "would defeat the queue that put it there",
            ),
            AuthzVariant(
                "reject",
                tenant_permission=_P.MEMORY_REJECT_TENANT,
                note="tenant-only, same reason as approve",
            ),
        ),
        note=(
            "The action comes from the validated transition, never a client-supplied "
            "string. Legal hold and the revision check still apply — authorization "
            "does not bypass them."
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
        # Reading a stored result is not cost-bearing; running one is.
        _S.TENANT, _ST.PLANNED, permission=_P.EVALS_READ
    ),
    # ── operator ────────────────────────────────────────────────────────────
    ("GET", "/api/admin/workers/health"): AuthzSpec(
        _S.OPERATOR, _ST.ENFORCED, permission=_P.WORKER_READ
    ),
}


def iter_routes_raw(app) -> Iterator[tuple[str, str]]:
    """Every (METHOD, path) registration, **including duplicates**.

    `iter_routes` deduplicates, which is right for generating the matrix and wrong
    for detecting a defect: registering `GET /api/example` twice would emit one
    entry, match one contract, and pass the guard — while the app has two handlers
    whose precedence depends on registration order.
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

    yield from walk(app.routes)


def iter_routes(app) -> Iterator[tuple[str, str]]:
    """Every distinct (METHOD, path) the application serves.

    Descends into included routers — `app.routes` is not flat in this FastAPI
    version, and a naive walk finds four paths and no API routes at all.
    """
    seen: set[tuple[str, str]] = set()
    for entry in iter_routes_raw(app):
        if entry not in seen:
            seen.add(entry)
            yield entry
