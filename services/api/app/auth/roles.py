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
Deliberately small. Five roles, a flat permission set, and a static mapping — no
hierarchy engine, no per-resource ACLs, no policy DSL. Permissions are checked at
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
    TRACES_READ_TENANT = "traces:read:tenant"
    EVIDENCE_READ = "evidence:read"
    RETENTION_READ = "retention:read"
    RETENTION_MANAGE = "retention:manage"
    CONSENT_MANAGE = "consent:manage"
    # Operations.
    WORKER_READ = "worker:read"
    WORKER_REPLAY = "worker:replay"
    SETTINGS_MANAGE = "settings:manage"
    #: Reading a stored evaluation result. Not cost-bearing.
    EVALS_READ = "evals:read"
    #: Executing an evaluation. Cost-bearing — a denial-of-wallet vector.
    EVALS_RUN = "evals:run"


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
            _P.TRACES_READ_TENANT,
            _P.EVIDENCE_READ,
            _P.RETENTION_READ,
            # Results are tenant-wide governance evidence, so this is an auditor
            # capability. memory_admin manages lifecycle and does not receive it.
            _P.EVALS_READ,
        }
    ),
    Role.TENANT_ADMIN: frozenset(set(Permission)),
    # Machine identity for the worker fleet: operational reads and replay, never
    # memory content or governance mutation.
    Role.SERVICE_WORKER: frozenset({_P.WORKER_READ, _P.WORKER_REPLAY}),
}

#: Applied only when a credential carries **no role claim at all** and the
#: deployment permits that fallback. Least privilege — never an admin default.
#:
#: A claim that is *present but contains no recognised role* gets **nothing**, not
#: this. Collapsing those two states would silently grant human memory permissions
#: to a mistyped credential: `roles=["service_workre"]` would resolve to
#: `memory_reader` and receive `memory:read:self` + `memory:write:self`. A typo must
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


def resolve_roles(raw: object) -> tuple[frozenset[Role], bool]:
    """Return `(roles, claim_present)` so callers can tell the four states apart.

    * claim omitted           -> `(frozenset(), False)`  — compatibility fallback
    * claim valid             -> `(roles, True)`
    * claim present, invalid  -> `(frozenset(), True)`   — zero permissions
    * claim present, empty    -> `(frozenset(), True)`   — zero permissions

    Presence is `raw is not None` and nothing more. Treating `[]` and `""` as
    absent conflated two different statements: an issuer that deliberately grants a
    credential **no roles** was indistinguishable from an older credential that
    predates roles entirely, so an explicitly empty role set silently received the
    `memory_reader` fallback — `memory:read:self` and `memory:write:self` for an
    identity the issuer said should have nothing.

    An omitted claim is a *compatibility* question the deployment answers
    (`auth_require_role_claim`). An empty claim is an *authorization decision the
    issuer already made*, and must be honoured.
    """
    return parse_roles(raw), raw is not None


def permissions_for(roles: frozenset[Role]) -> frozenset[Permission]:
    """Union of every permission granted by the given roles."""
    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(granted)
