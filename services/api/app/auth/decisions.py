"""The four authorization helpers every governed route uses.

Separate helpers rather than one with many optional arguments: a route that needs a
fixed capability, a route that resolves a requested subject, a route that loads a
record first, and a route whose action decides the permission are four different
questions. Collapsing them into one signature makes every call site look plausible
while doing something subtly different.

Each helper returns the **trusted** values the handler must use from that point on,
and records a content-free witness so a route cannot be called enforced without
evidence the check ran.

The rule that makes this work
-----------------------------
When a variant declares no self permission — `approve`, `reject` — the tenant
permission is required *even on the caller's own record*. Ownership must not convert
tenant governance into self-service: a user approving their own pending sensitive
memory would defeat the queue that put it there. `authorize_loaded_resource` treats
a missing self branch as "tenant-only", never as "own record, therefore allowed".
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from .dependencies import current_principal
from .principal import Principal
from .roles import Permission
from .witness import AuthzDecision, record_decision, route_of


@dataclass(frozen=True)
class AuthorizedSubject:
    """The tenant/user a handler is permitted to query.

    These are the *only* values that may reach the repository. Returning the
    caller's requested values after validating them would leave untrusted input in
    the query path, which is not authorization.
    """

    tenant_id: str
    user_id: str | None
    tenant_scoped: bool


@dataclass(frozen=True)
class AuthorizationDecision:
    """The outcome of an ownership-based check."""

    permission: Permission
    tenant_scoped: bool
    action: str | None = None


def _witness(
    request: Request,
    *,
    helper: str,
    permission: Permission | None,
    action: str | None = None,
    tenant_scoped: bool = False,
) -> None:
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


def _require(principal: Principal, permission: Permission) -> None:
    if not principal.has(permission):
        raise HTTPException(
            status_code=403,
            detail=f"missing required permission '{permission.value}'",
        )


def authorize_subject_scope(
    request: Request,
    *,
    requested_tenant_id: str,
    requested_user_id: str | None,
    self_permission: Permission,
    tenant_permission: Permission,
) -> AuthorizedSubject:
    """Resolve which subject the caller may query, and force the query to it.

    Used by collection routes, where no stored record exists to inspect ownership
    on. Omitting the user is how `/api/audit` silently returned tenant-wide records:
    the scope middleware only validates a `user_id` that is *present*.
    """
    principal = current_principal(request)
    if principal is None:
        # Auth disabled: unchanged development behaviour. Production refuses to start
        # with auth_mode=none, so this path cannot reach it.
        return AuthorizedSubject(requested_tenant_id, requested_user_id, tenant_scoped=False)

    if requested_tenant_id != principal.tenant_id:
        raise HTTPException(
            status_code=403,
            detail="request scope does not match authenticated principal",
        )

    # An *omitted* subject is treated as a tenant-wide request, not as an implicit
    # "my own". Omitting it is precisely how /api/audit silently returned
    # tenant-wide records — the scope middleware only validates a `user_id` that is
    # present. Reinterpreting an unscoped request as self-scoped would succeed with
    # narrower data instead of failing, silently changing what the caller asked for
    # and reversing the 403 established in #115. Callers wanting their own rows name
    # themselves.
    wants_tenant_wide = requested_user_id is None or requested_user_id != principal.user_id
    if wants_tenant_wide:
        _require(principal, tenant_permission)
        _witness(
            request,
            helper="subject",
            permission=tenant_permission,
            tenant_scoped=True,
        )
        return AuthorizedSubject(principal.tenant_id, requested_user_id, tenant_scoped=True)

    _require(principal, self_permission)
    _witness(request, helper="subject", permission=self_permission)
    # Forced to the principal, not echoed back from the request.
    return AuthorizedSubject(principal.tenant_id, principal.user_id, tenant_scoped=False)


def authorize_loaded_resource(
    request: Request,
    *,
    resource_tenant_id: str,
    resource_user_id: str,
    self_permission: Permission | None,
    tenant_permission: Permission | None,
    action: str | None = None,
) -> AuthorizationDecision:
    """Decide from the *stored* record's ownership, never from request values.

    `self_permission=None` marks a tenant-only action. Ownership then does not
    grant it: `approve` on your own pending memory still requires
    `memory:approve:tenant`.
    """
    principal = current_principal(request)
    if principal is None:
        return AuthorizationDecision(
            permission=self_permission or tenant_permission,  # type: ignore[arg-type]
            tenant_scoped=False,
            action=action,
        )

    if resource_tenant_id != principal.tenant_id:
        # Conceal existence across tenants — 403 would confirm the record is real.
        raise HTTPException(status_code=404, detail="memory not found")

    owns_it = resource_user_id == principal.user_id

    if owns_it and self_permission is not None:
        required, tenant_scoped = self_permission, False
    else:
        if tenant_permission is None:
            raise HTTPException(
                status_code=403,
                detail=f"action '{action or 'operation'}' is not permitted",
            )
        required, tenant_scoped = tenant_permission, True

    if not principal.has(required):
        # Another user's record: hide it rather than confirm it exists.
        if not owns_it:
            raise HTTPException(status_code=404, detail="memory not found")
        raise HTTPException(
            status_code=403,
            detail=f"missing required permission '{required.value}'",
        )

    _witness(
        request,
        helper="resource",
        permission=required,
        action=action,
        tenant_scoped=tenant_scoped,
    )
    return AuthorizationDecision(permission=required, tenant_scoped=tenant_scoped, action=action)


def authorize_transition(
    request: Request,
    *,
    spec,
    validated_action: str,
    resource_tenant_id: str,
    resource_user_id: str,
) -> AuthorizationDecision:
    """Authorize one validated action on a loaded record.

    `validated_action` comes from the transition the server already validated, never
    from a client-supplied action string.
    """
    variant = spec.variant(validated_action)
    if variant is None:
        # A contract error, not a caller error: the handler derived an action the
        # route never declared. Fail closed rather than fall back to a route-level
        # permission — that fallback is what commit 1b removed.
        raise HTTPException(
            status_code=500,
            detail=f"no authorization contract for action '{validated_action}'",
        )

    decision = authorize_loaded_resource(
        request,
        resource_tenant_id=resource_tenant_id,
        resource_user_id=resource_user_id,
        self_permission=variant.self_permission,
        tenant_permission=variant.tenant_permission,
        action=validated_action,
    )
    _witness(
        request,
        helper="transition",
        permission=decision.permission,
        action=validated_action,
        tenant_scoped=decision.tenant_scoped,
    )
    return decision
