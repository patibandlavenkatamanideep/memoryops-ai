"""Auth + authorization adapters (v1.6, ADR-020).

Identity-neutral: MemoryOps verifies an identity an upstream issuer minted (trusted
header or bearer JWT) and enforces that every memory operation is scoped to the
authenticated tenant/user. It is not an auth product. Off by default.
"""

from __future__ import annotations

from .dependencies import current_principal, enforce_scope
from .jwt import JWTError, decode_jwt
from .middleware import install_auth_middleware
from .principal import Principal
from .providers import JWTProvider, TrustedHeaderProvider, build_provider

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
]
