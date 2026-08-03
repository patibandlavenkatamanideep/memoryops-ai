"""In-route scope enforcement for body routes + a Principal accessor.

Body routes (chat, retention) can't be scoped from the query string, so they call
`enforce_scope(request, tenant_id, user_id)` after the body is parsed. It is a no-op
when auth is disabled (no principal attached), so default behavior is unchanged.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from .principal import Principal
from .roles import Permission


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
        return user_id
    return principal.user_id
