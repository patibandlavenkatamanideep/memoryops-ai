"""Auth + authorization adapters (v1.6, ADR-020).

Identity-neutral: MemoryOps verifies an identity an upstream issuer minted (trusted
header or bearer JWT) and enforces that every memory operation is scoped to the
authenticated tenant/user. It is not an auth product. Off by default.
"""

from __future__ import annotations

from .dependencies import (
    authorize_audit_scope,
    current_principal,
    enforce_scope,
    require_permission,
)
from .jwt import JWTError, decode_jwt
from .middleware import install_auth_middleware
from .principal import Principal
from .providers import JWTProvider, TrustedHeaderProvider, build_provider
from .roles import DEFAULT_ROLE, Permission, Role, parse_roles, permissions_for
from .witness import AuthzDecision, AuthzWitness, witness_for

__all__ = [
    "Principal",
    "JWTError",
    "decode_jwt",
    "JWTProvider",
    "TrustedHeaderProvider",
    "build_provider",
    "install_auth_middleware",
    "current_principal",
    "enforce_scope",
    "require_permission",
    "authorize_audit_scope",
    "Permission",
    "Role",
    "DEFAULT_ROLE",
    "parse_roles",
    "permissions_for",
    "AuthzWitness",
    "AuthzDecision",
    "witness_for",
]
