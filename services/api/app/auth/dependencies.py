"""In-route scope enforcement for body routes + a Principal accessor.

Body routes (chat, retention) can't be scoped from the query string, so they call
`enforce_scope(request, tenant_id, user_id)` after the body is parsed. It is a no-op
when auth is disabled (no principal attached), so default behavior is unchanged.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from .principal import Principal
from .roles import Permission
from .witness import AuthzDecision, record_decision, route_of


def _witness(
    request: Request,
    *,
    helper: str,
    permission: Permission | None = None,
    action: str | None = None,
    tenant_scoped: bool = False,
) -> None:
    """Record that a check ran, so a route cannot be *called* enforced without it."""
    route = route_of(request)
    if route is None:
        return
    record_decision(
        request,
        AuthzDecision(
            route=route,
            helper=helper,
            permission=permission,
            action=action,
            tenant_scoped=tenant_scoped,
        ),
    )


def current_principal(request: Request) -> Principal | None:
    """The authenticated principal, or None when auth is disabled."""
    return getattr(request.state, "principal", None)


def enforce_scope(request: Request, tenant_id: str, user_id: str) -> None:
    """Assert the request's tenant/user match the authenticated principal.

    No-op when auth is off (no principal). When on, the middleware has already
    guaranteed a principal exists for guarded routes; here we check the *body*
    values a caller supplied cannot cross into another tenant/user.
    """
    principal = current_principal(request)
    if principal is None:
        return
    if tenant_id != principal.tenant_id or user_id != principal.user_id:
        raise HTTPException(
            status_code=403,
            detail="request scope does not match authenticated principal",
        )


def _auth_enabled() -> bool:
    """Whether an identity provider is configured at all.

    Read at call time, not import time: tests and the playground flip the mode
    between requests, and a cached value would make the check answer for the wrong
    configuration.
    """
    from ..core.config import get_settings

    return get_settings().auth_mode != "none"


def require_authenticated(request: Request) -> Principal | None:
    """Assert there is an authenticated caller, with no further capability required.

    Implements the `authenticated` scope for routes that expose nothing tenant-
    specific — the static loop *definitions*, which are product documentation
    identical for every caller and carry no prompts, configuration, or tenant data
    (asserted in `tests/test_governance_read_boundary.py`).

    The alternative was to give them some existing permission so the witness had one
    to record. That would be a lie in the matrix: the route would claim to enforce a
    capability it does not need, and the first person to widen that permission for an
    unrelated reason would silently change who can read these. A scope that means
    "any verified caller" should be enforced as exactly that.

    Returns the principal, or `None` when auth is disabled — matching
    `enforce_scope` / `require_permission`, and safe because
    `MEMORYOPS_PROFILE=production` refuses to start with `auth_mode=none`. The 401 for
    a missing credential is issued by the middleware before the route runs; this is
    the in-route counterpart for anything the middleware does not cover.
    """
    principal = current_principal(request)
    if principal is None:
        if _auth_enabled():
            raise HTTPException(status_code=401, detail="missing or invalid credentials")
        return None
    _witness(request, helper="require_authenticated")
    return principal


def require_permission(request: Request, permission: Permission) -> Principal | None:
    """Assert the caller holds `permission`; 403 otherwise.

    No-op when auth is disabled (no principal), matching `enforce_scope`. That keeps
    the zero-infra demo and the offline test suite working, and is safe because
    `MEMORYOPS_PROFILE=production` refuses to start with `auth_mode=none`.

    Returns the principal so callers can scope further (e.g. narrowing a tenant-wide
    query to the caller's own user when they lack the tenant-wide permission).
    """
    principal = current_principal(request)
    if principal is None:
        return None
    if not principal.has(permission):
        raise HTTPException(
            status_code=403,
            detail=f"missing required permission '{permission.value}'",
        )
    _witness(request, helper="require_permission", permission=permission)
    return principal


def authorize_audit_scope(
    request: Request, tenant_id: str, user_id: str | None
) -> str | None:
    """Resolve the audit query's effective user scope, or refuse.

    The hole this closes: `/api/audit` took `tenant_id` from the query string with
    `user_id` optional and applied no authorization at all. Because the
    scope-validation middleware only checks a `user_id` that is *present*, omitting
    it skipped validation and the route returned **tenant-wide** records. Verified
    with auth on: alice requesting `?tenant_id=acme` received bob's audit rows.

    Rules:
      * no principal (auth disabled) → unchanged behaviour;
      * tenant-wide request (no `user_id`, or another user's) requires
        `audit:read:tenant`;
      * otherwise the query is forced to the caller's own `user_id`.
    """
    principal = current_principal(request)
    if principal is None:
        return user_id

    if tenant_id != principal.tenant_id:
        raise HTTPException(
            status_code=403,
            detail="request scope does not match authenticated principal",
        )

    wants_tenant_wide = user_id is None or user_id != principal.user_id
    if wants_tenant_wide:
        if not principal.has(Permission.AUDIT_READ_TENANT):
            raise HTTPException(
                status_code=403,
                detail=(
                    "tenant-wide audit requires 'audit:read:tenant'; "
                    "omit the scope only with an auditor or admin credential"
                ),
            )
        _witness(
            request,
            helper="authorize_audit_scope",
            permission=Permission.AUDIT_READ_TENANT,
            tenant_scoped=True,
        )
        return user_id
    _witness(
        request,
        helper="authorize_audit_scope",
        permission=Permission.AUDIT_READ_SELF,
    )
    # Force the query to the caller. Validating the supplied value and then
    # continuing to use it would not be authorization.
    return principal.user_id
