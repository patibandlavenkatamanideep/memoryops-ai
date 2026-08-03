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

    # Memory lifecycle, scoped to the caller's own user.
    MEMORY_READ_SELF = "memory:read:self"
    MEMORY_WRITE_SELF = "memory:write:self"
    # Tenant-wide memory management (any user in the tenant).
    MEMORY_READ_TENANT = "memory:read:tenant"
    MEMORY_APPROVE = "memory:approve"
    MEMORY_ARCHIVE = "memory:archive"
    MEMORY_DELETE = "memory:delete"
    # Governance and evidence surfaces.
    AUDIT_READ_SELF = "audit:read:self"
    AUDIT_READ_TENANT = "audit:read:tenant"
    METRICS_READ_TENANT = "metrics:read:tenant"
    TRACES_READ_TENANT = "traces:read:tenant"
    EVIDENCE_READ = "evidence:read"
    RETENTION_MANAGE = "retention:manage"
    CONSENT_MANAGE = "consent:manage"
    # Operations.
    WORKER_READ = "worker:read"
    WORKER_REPLAY = "worker:replay"
    SETTINGS_MANAGE = "settings:manage"
    EVALS_RUN = "evals:run"


class Role(str, Enum):
    """Named bundles of permissions. Kept few on purpose."""

    MEMORY_READER = "memory_reader"
    MEMORY_ADMIN = "memory_admin"
    AUDITOR = "auditor"
    TENANT_ADMIN = "tenant_admin"
    SERVICE_WORKER = "service_worker"


_P = Permission

#: Static role → permission mapping. A role is only a name for a bundle; every
#: check is against a permission, so adding a role never implicitly grants access
#: to an endpoint that did not ask for its permission.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    # The default for an authenticated caller with no recognised role claim.
    # Least privilege: read and write *their own* memory, read *their own* audit.
    Role.MEMORY_READER: frozenset(
        {_P.MEMORY_READ_SELF, _P.MEMORY_WRITE_SELF, _P.AUDIT_READ_SELF}
    ),
    Role.MEMORY_ADMIN: frozenset(
        {
            _P.MEMORY_READ_SELF,
            _P.MEMORY_WRITE_SELF,
            _P.MEMORY_READ_TENANT,
            _P.MEMORY_APPROVE,
            _P.MEMORY_ARCHIVE,
            _P.MEMORY_DELETE,
            _P.AUDIT_READ_SELF,
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
DEFAULT_ROLE = Role.MEMORY_READER


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

    known = {r.value: r for r in Role}
    return frozenset(known[c.strip()] for c in candidates if c.strip() in known)


def resolve_roles(raw: object) -> tuple[frozenset[Role], bool]:
    """Return `(roles, claim_present)` so callers can tell the three states apart.

    * claim absent            -> `(frozenset(), False)`
    * claim valid             -> `(roles, True)`
    * claim present, invalid  -> `(frozenset(), True)`

    The third case must not fall back to a default role.
    """
    present = raw is not None and raw != "" and raw != []
    return parse_roles(raw), present


def permissions_for(roles: frozenset[Role]) -> frozenset[Permission]:
    """Union of every permission granted by the given roles."""
    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(granted)
