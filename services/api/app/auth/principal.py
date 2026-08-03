"""The authenticated caller identity resolved from a request."""

from __future__ import annotations

from dataclasses import dataclass, field

from .roles import DEFAULT_ROLE, Permission, Role, permissions_for


@dataclass(frozen=True)
class Principal:
    """Who the caller is, after the identity layer has verified them.

    `tenant_id` / `user_id` are authoritative — routes must scope every memory
    operation to these, never to unverified values from the request body.

    `roles` answers the question authentication does not: *may you do this?*
    Before it existed, any authenticated user could read tenant-wide audit records
    simply by omitting `user_id` from the query string.
    """

    tenant_id: str
    user_id: str
    provider: str  # trusted_header | jwt | none
    claims: dict = field(default_factory=dict)
    #: Roles carried by the credential. Empty means "no recognised role claim",
    #: which resolves to `DEFAULT_ROLE` (least privilege) rather than to nothing —
    #: an authenticated caller can still manage their own memory.
    roles: frozenset[Role] = field(default_factory=frozenset)
    #: Stable identifier for the acting entity, for audit. Falls back to `user_id`.
    actor_id: str = ""
    #: True for machine credentials (the worker fleet), scoped to operational
    #: permissions and never to memory content.
    is_service_account: bool = False

    @property
    def effective_roles(self) -> frozenset[Role]:
        return self.roles or frozenset({DEFAULT_ROLE})

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_for(self.effective_roles)

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions

    @property
    def actor(self) -> str:
        return self.actor_id or self.user_id
