"""Roles and permissions for API-level authorization.

Why this exists
---------------
The API authenticated callers but never authorized them. `Principal` carried
`tenant_id`, `user_id`, `provider` and `claims` — no role, no permission. So
authentication answered *who are you?* and nothing answered *may you do this?*

Reproduced with authentication **on** (`MEMORYOPS_AUTH_MODE=trusted_header`):

    alice GET /api/audit?tenant_id=acme        -> 200
    audit rows returned for users: {'alice', 'bob'}

An ordinary user read another user's audit trail inside their tenant. The
scope-validation middleware checks query-string `tenant_id`/`user_id`, so omitting
`user_id` skipped the check entirely and the route defaulted to tenant-wide.

The web control plane (#112) added role checks, but those live in the Next.js BFF.
A caller talking to the API directly bypasses all of them. Authorization has to be
enforced here or it is not enforced at all.

Design
------
Deliberately small: a fixed role set, a flat permission set, and a static mapping —
no hierarchy engine, no per-resource ACLs, no policy DSL. Permissions are checked at
the route; roles are only a way to name bundles of them.

MemoryOps stays identity-neutral: roles arrive as claims from whatever issuer you
already run (see `docs/auth-adapters.md`). This is authorization enforcement plus
adapter patterns — **not** a replacement for an identity provider.
"""

from __future__ import annotations

from enum import Enum


class Permission(str, Enum):
    """What a caller may do. Checked directly by routes."""

    # Memory lifecycle. Scope is part of the permission name: "may I do this to my
    # own records, or to anyone's in the tenant?" are different powers, and an
    # unscoped `memory:delete` could not express the difference.
    MEMORY_READ_SELF = "memory:read:self"
    MEMORY_READ_TENANT = "memory:read:tenant"
    MEMORY_WRITE_SELF = "memory:write:self"
    MEMORY_WRITE_TENANT = "memory:write:tenant"
    MEMORY_ARCHIVE_SELF = "memory:archive:self"
    MEMORY_ARCHIVE_TENANT = "memory:archive:tenant"
    MEMORY_DELETE_SELF = "memory:delete:self"
    MEMORY_DELETE_TENANT = "memory:delete:tenant"
    # Approval is tenant governance by definition: a user approving their own
    # pending sensitive memory would defeat the queue that put it there.
    MEMORY_APPROVE_TENANT = "memory:approve:tenant"
    MEMORY_REJECT_TENANT = "memory:reject:tenant"
    # Governance and evidence surfaces.
    AUDIT_READ_SELF = "audit:read:self"
    AUDIT_READ_TENANT = "audit:read:tenant"
    METRICS_READ_TENANT = "metrics:read:tenant"
    EVIDENCE_READ = "evidence:read"
    RETENTION_READ = "retention:read"
    RETENTION_MANAGE = "retention:manage"
    CONSENT_MANAGE = "consent:manage"
    # Operations.
    WORKER_READ = "worker:read"
    WORKER_REPLAY = "worker:replay"
    SETTINGS_MANAGE = "settings:manage"
    # Deployment operations. These act on the process or the whole installation, not
    # on one tenant's data, so no tenant role holds them however senior it is —
    # "administrator of tenant A" and "operator of this deployment" are different
    # authorities, and conflating them lets one customer act for all of them.
    OPS_EVALS_READ = "ops:evals:read"
    OPS_EVALS_RUN = "ops:evals:run"
    OPS_TRACES_READ = "ops:traces:read"
    OPS_METRICS = "ops:metrics"
    OPS_READINESS = "ops:readiness"


class Role(str, Enum):
    """Named bundles of permissions. Kept few on purpose.

    These are the *authorization* vocabulary. The web app has its own *persona*
    vocabulary (viewer / developer / auditor / memory_admin / owner); the two are
    joined by `contracts/auth-role-map.json`, not by matching strings. Minting a web
    persona name straight into an API credential left three of the five human roles
    naming nothing the API recognised.
    """

    MEMORY_VIEWER = "memory_viewer"
    MEMORY_USER = "memory_user"
    AUDITOR = "auditor"
    MEMORY_ADMIN = "memory_admin"
    TENANT_ADMIN = "tenant_admin"
    SERVICE_WORKER = "service_worker"
    #: Runs the deployment. Not a tenant role and not reachable by escalation within
    #: one — a platform operator sees process-wide state and spends platform compute,
    #: neither of which belongs to any single customer.
    PLATFORM_OPERATOR = "platform_operator"


#: Accepted role names that are not `Role` values. `memory_reader` shipped in the
#: first RBAC release and could already write, so the name was misleading: it is a
#: self-service memory *user*, not a reader. Kept so existing credentials keep
#: working while the accurate name becomes canonical.
ROLE_ALIASES: dict[str, Role] = {
    "memory_reader": Role.MEMORY_USER,
}


_P = Permission

#: Static role → permission mapping. A role is only a name for a bundle; every
#: check is against a permission, so adding a role never implicitly grants access
#: to an endpoint that did not ask for its permission.
_SELF_MEMORY = frozenset(
    {
        _P.MEMORY_READ_SELF,
        _P.MEMORY_WRITE_SELF,
        _P.MEMORY_ARCHIVE_SELF,
        # Self-deletion belongs to an ordinary user. Removing your own memory is a
        # user-control guarantee; requiring tenant-admin for it would invert that.
        _P.MEMORY_DELETE_SELF,
        _P.AUDIT_READ_SELF,
    }
)

#: Everything a tenant administrator may do. Written out rather than computed.
#:
#: This was `frozenset(set(Permission))` — "whatever exists". That is a standing
#: hazard rather than a shortcut: any permission added anywhere, for any reason,
#: silently became tenant-admin authority the moment it was defined, with no decision
#: and no diff at the grant site. A deployment capability introduced for operators
#: would have been handed to every tenant admin without anyone choosing that.
#:
#: Listing it explicitly means a new permission is *not* granted until someone writes
#: it down. `tests/test_tenant_admin_bundle.py` fails while a permission is neither
#: granted here nor recorded in `_NOT_TENANT_SCOPED` with a reason.
#:
#: This bundle explicitly contains every tenant-scoped permission. Permissions
#: excluded as deployment-level or machine-only authority are recorded in
#: `_NOT_TENANT_SCOPED` with a reason.
_TENANT_ADMIN: frozenset[Permission] = frozenset(
    {
        # Memory lifecycle, tenant-wide.
        _P.MEMORY_READ_SELF,
        _P.MEMORY_READ_TENANT,
        _P.MEMORY_WRITE_SELF,
        _P.MEMORY_WRITE_TENANT,
        _P.MEMORY_ARCHIVE_SELF,
        _P.MEMORY_ARCHIVE_TENANT,
        _P.MEMORY_DELETE_SELF,
        _P.MEMORY_DELETE_TENANT,
        _P.MEMORY_APPROVE_TENANT,
        _P.MEMORY_REJECT_TENANT,
        # Governance + evidence.
        _P.AUDIT_READ_SELF,
        _P.AUDIT_READ_TENANT,
        _P.METRICS_READ_TENANT,
        _P.EVIDENCE_READ,
        _P.RETENTION_READ,
        _P.RETENTION_MANAGE,
        _P.CONSENT_MANAGE,
        # Tenant configuration.
        _P.SETTINGS_MANAGE,
    }
)

#: Permissions deliberately withheld from `_TENANT_ADMIN`, each with the reason, so an
#: exclusion reads as a decision rather than an oversight.
_NOT_TENANT_SCOPED: dict[Permission, str] = {
    _P.WORKER_READ: "worker fleet health is deployment state, not one tenant's data",
    _P.WORKER_REPLAY: "replaying a job affects the deployment, not one tenant",
    _P.OPS_EVALS_READ: "evaluation results are deployment-wide; the harness runs "
    "against its own fixtures and the result store has no tenant dimension",
    _P.OPS_EVALS_RUN: "executing the harness is platform compute — one tenant must "
    "not be able to spend it or replace the result every other tenant reads",
    _P.OPS_TRACES_READ: "the span buffer is process-wide and carries no tenant "
    "dimension, so reading it is deployment observability",
    _P.OPS_METRICS: "process-wide Prometheus exposition, not per-tenant counts",
    _P.OPS_READINESS: "dependency and configuration state for the installation",
}


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    # Read-only persona.
    Role.MEMORY_VIEWER: frozenset({_P.MEMORY_READ_SELF, _P.AUDIT_READ_SELF}),
    # The default for an authenticated caller with no role claim, where the
    # deployment permits that fallback. Full self-service over their own records.
    Role.MEMORY_USER: _SELF_MEMORY,
    Role.MEMORY_ADMIN: _SELF_MEMORY
    | frozenset(
        {
            _P.MEMORY_READ_TENANT,
            _P.MEMORY_WRITE_TENANT,
            _P.MEMORY_ARCHIVE_TENANT,
            _P.MEMORY_DELETE_TENANT,
            _P.MEMORY_APPROVE_TENANT,
            _P.MEMORY_REJECT_TENANT,
            _P.RETENTION_READ,
            _P.RETENTION_MANAGE,
            _P.CONSENT_MANAGE,
        }
    ),
    # Reads governance evidence across the tenant; deliberately cannot mutate
    # memory — an auditor who can edit what they audit is not an auditor.
    Role.AUDITOR: frozenset(
        {
            _P.MEMORY_READ_SELF,
            _P.MEMORY_READ_TENANT,
            _P.AUDIT_READ_SELF,
            _P.AUDIT_READ_TENANT,
            _P.METRICS_READ_TENANT,
            _P.EVIDENCE_READ,
            _P.RETENTION_READ,
        }
    ),
    Role.TENANT_ADMIN: _TENANT_ADMIN,
    # Machine identity for the worker fleet: operational reads and replay, never
    # memory content or governance mutation.
    Role.SERVICE_WORKER: frozenset({_P.WORKER_READ, _P.WORKER_REPLAY}),
    # Deployment authority. Deliberately holds no memory, audit, or governance
    # permission: operating the platform does not include reading what customers
    # stored in it. Distinct from `service_worker`, which is the worker fleet's own
    # machine identity and may replay jobs but never inspect the deployment at large.
    Role.PLATFORM_OPERATOR: frozenset(
        {
            _P.OPS_EVALS_READ,
            _P.OPS_EVALS_RUN,
            _P.OPS_TRACES_READ,
            _P.OPS_METRICS,
            _P.OPS_READINESS,
            # Fleet health is deployment state. `service_worker` also holds this for
            # its own self-reporting; an operator needs it to run the installation.
            _P.WORKER_READ,
        }
    ),
}

#: Applied only when a credential carries **no role claim at all** and the
#: deployment permits that fallback. Least privilege — never an admin default.
#:
#: A claim that is *present but contains no recognised role* gets **nothing**, not
#: this. Collapsing those two states would silently grant human memory permissions
#: to a mistyped credential: `roles=["service_workre"]` would resolve to
#: `memory_user` and receive `memory:read:self` + `memory:write:self`. A typo must
#: not grant anything.
DEFAULT_ROLE = Role.MEMORY_USER


def parse_roles(raw: object) -> frozenset[Role]:
    """Map a claim value onto known roles, ignoring anything unrecognised.

    Accepts a list (``["auditor"]``), a space/comma-separated string, or a single
    name. Unknown names are dropped silently: an issuer sending `"admin"` must not
    accidentally match `tenant_admin`, and a typo must not escalate.
    """
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        candidates = [part for part in raw.replace(",", " ").split() if part]
    elif isinstance(raw, list | tuple | set | frozenset):
        candidates = [str(part) for part in raw]
    else:
        return frozenset()

    known = {r.value: r for r in Role} | ROLE_ALIASES
    return frozenset(known[c.strip()] for c in candidates if c.strip() in known)


def resolve_roles(
    raw: object, *, claim_present: bool | None = None
) -> tuple[frozenset[Role], bool]:
    """Return `(roles, claim_present)` so callers can tell the four states apart.

    * claim omitted           -> `(frozenset(), False)`  — compatibility fallback
    * claim valid             -> `(roles, True)`
    * claim present, invalid  -> `(frozenset(), True)`   — zero permissions
    * claim present, empty    -> `(frozenset(), True)`   — zero permissions

    Treating `[]` and `""` as absent conflated two different statements: an issuer
    that deliberately grants a credential **no roles** was indistinguishable from an
    older credential that predates roles entirely, so an explicitly empty role set
    silently received the `memory_user` fallback — `memory:read:self` and
    `memory:write:self` for an identity the issuer said should have nothing.

    An omitted claim is a *compatibility* question the deployment answers
    (`auth_require_role_claim`). An empty claim is an *authorization decision the
    issuer already made*, and must be honoured.

    `claim_present` lets a caller state presence it knows independently of the value.
    A JSON `null` is a *present* claim whose value is `None`, and no inspection of
    the value can reveal that — the default `raw is not None` would read it as
    omitted and hand back the fallback. Header-based callers omit the argument: for
    them an absent header really is `None`, and an empty header is `""`.
    """
    present = (raw is not None) if claim_present is None else claim_present
    return parse_roles(raw), present


def permissions_for(roles: frozenset[Role]) -> frozenset[Permission]:
    """Union of every permission granted by the given roles."""
    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(granted)
