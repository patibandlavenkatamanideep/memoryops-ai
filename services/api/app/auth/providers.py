"""Identity providers — resolve a `Principal` from an incoming request.

MemoryOps is identity-neutral: bring your own issuer. Two adapters cover the
common integrations:

- `TrustedHeaderProvider` — an upstream, already-authenticated gateway/proxy
  (Clerk/Auth0/Supabase edge, an API gateway, or your own BFF) injects the tenant
  and user as headers. This is the **bring-your-own-auth** pattern.
- `JWTProvider` — MemoryOps itself verifies a `Authorization: Bearer <jwt>` and
  maps configured claims to tenant/user. Works with Clerk, Auth0, Supabase, or any
  standard JWT issuer by pointing `tenant_claim` / `user_claim` at the right claims
  (see `docs/auth-adapters.md`).

Providers never raise for *server* reasons — a missing/invalid credential returns
`None` (→ 401) and never a 500.
"""

from __future__ import annotations

from typing import Protocol

from .jwt import JWTError, claim_node, claim_path, decode_jwt
from .principal import Principal
from .roles import resolve_roles


class IdentityProvider(Protocol):
    def resolve(self, headers: HeaderMap) -> Principal | None: ...


class HeaderMap(Protocol):
    def get(self, key: str, default: str | None = None) -> str | None: ...


class TrustedHeaderProvider:
    """Trust tenant/user headers injected by an authenticated upstream proxy."""

    def __init__(
        self,
        tenant_header: str,
        user_header: str,
        roles_header: str = "",
        actor_type_header: str = "",
        require_role_claim: bool = False,
    ) -> None:
        self._tenant_header = tenant_header
        self._user_header = user_header
        self._roles_header = roles_header
        self._actor_type_header = actor_type_header
        self._require_role_claim = require_role_claim

    def resolve(self, headers: HeaderMap) -> Principal | None:
        tenant = headers.get(self._tenant_header.lower())
        user = headers.get(self._user_header.lower())
        if not tenant or not user:
            return None
        raw_roles = headers.get(self._roles_header.lower()) if self._roles_header else None
        roles, claim_present = resolve_roles(raw_roles)
        actor_type = (
            headers.get(self._actor_type_header.lower()) if self._actor_type_header else None
        )
        return Principal(
            tenant_id=tenant,
            user_id=user,
            provider="trusted_header",
            roles=roles,
            role_claim_present=claim_present,
            require_role_claim=self._require_role_claim,
            actor_id=user,
            is_service_account=(actor_type or "").strip().lower() == "service_account",
        )


class JWTProvider:
    """Verify a bearer JWT and map claims to tenant/user."""

    def __init__(
        self,
        *,
        key: str,
        algorithms: list[str],
        tenant_claim: str,
        user_claim: str,
        roles_claim: str = "roles",
        actor_type_claim: str = "actor_type",
        require_role_claim: bool = False,
        audience: str | None = None,
        issuer: str | None = None,
        jwks_url: str | None = None,
    ) -> None:
        self._key = key
        self._algorithms = algorithms
        self._tenant_claim = tenant_claim
        self._user_claim = user_claim
        self._roles_claim = roles_claim
        self._actor_type_claim = actor_type_claim
        self._require_role_claim = require_role_claim
        self._audience = audience
        self._issuer = issuer
        self._jwks_url = jwks_url

    def resolve(self, headers: HeaderMap) -> Principal | None:
        auth = headers.get("authorization")
        if not auth or not auth.lower().startswith("bearer "):
            return None
        token = auth[7:].strip()
        try:
            payload = decode_jwt(
                token,
                key=self._key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                jwks_url=self._jwks_url,
            )
        except JWTError:
            return None
        tenant = claim_path(payload, self._tenant_claim)
        user = claim_path(payload, self._user_claim)
        if not tenant or not user:
            return None
        # `claim_node`, not `claim_path`: a roles claim is normally a JSON array, and
        # stringifying containers turned `["auditor"]` into "no claim at all".
        roles, claim_present = resolve_roles(claim_node(payload, self._roles_claim))
        return Principal(
            tenant_id=tenant,
            user_id=user,
            provider="jwt",
            claims=payload,
            roles=roles,
            role_claim_present=claim_present,
            require_role_claim=self._require_role_claim,
            actor_id=str(claim_path(payload, "sub") or user),
            is_service_account=(
                str(claim_path(payload, self._actor_type_claim) or "").strip().lower()
                == "service_account"
            ),
        )


def build_provider(settings) -> IdentityProvider | None:
    """Construct the configured provider, or None when auth is disabled."""
    mode = settings.auth_mode
    if mode == "none":
        return None
    if mode == "trusted_header":
        return TrustedHeaderProvider(
            settings.auth_tenant_header,
            settings.auth_user_header,
            getattr(settings, "auth_roles_header", "") or "",
            getattr(settings, "auth_actor_type_header", "") or "",
            bool(getattr(settings, "auth_require_role_claim", False)),
        )
    if mode == "jwt":
        algs = [a.strip() for a in settings.auth_jwt_algorithms.split(",") if a.strip()]
        return JWTProvider(
            key=settings.auth_jwt_key,
            algorithms=algs,
            tenant_claim=settings.auth_jwt_tenant_claim,
            user_claim=settings.auth_jwt_user_claim,
            roles_claim=getattr(settings, "auth_jwt_roles_claim", "roles"),
            actor_type_claim=getattr(settings, "auth_jwt_actor_type_claim", "actor_type"),
            require_role_claim=bool(getattr(settings, "auth_require_role_claim", False)),
            audience=settings.auth_jwt_audience or None,
            issuer=settings.auth_jwt_issuer or None,
            jwks_url=getattr(settings, "auth_jwt_jwks_url", "") or None,
        )
    return None
