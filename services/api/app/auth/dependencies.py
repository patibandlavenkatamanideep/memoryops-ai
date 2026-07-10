"""In-route scope enforcement for body routes + a Principal accessor.

Body routes (chat, retention) can't be scoped from the query string, so they call
`enforce_scope(request, tenant_id, user_id)` after the body is parsed. It is a no-op
when auth is disabled (no principal attached), so default behavior is unchanged.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from .principal import Principal


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
