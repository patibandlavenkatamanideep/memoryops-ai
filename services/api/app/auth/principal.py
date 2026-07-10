"""The authenticated caller identity resolved from a request."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Principal:
    """Who the caller is, after the identity layer has verified them.

    `tenant_id` / `user_id` are authoritative — routes must scope every memory
    operation to these, never to unverified values from the request body.
    """

    tenant_id: str
    user_id: str
    provider: str  # trusted_header | jwt | none
    claims: dict = field(default_factory=dict)
