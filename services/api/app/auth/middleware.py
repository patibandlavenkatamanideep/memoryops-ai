"""Tenant/user scope-validation middleware (v1.6, ADR-020).

Off by default (`auth_mode="none"`) so nothing changes until an operator opts in.
When enabled it does two things for every `/api/*` request:

1. **Authenticate** — resolve a `Principal` from the configured provider (a trusted
   upstream header, or a verified bearer JWT). No credential ⇒ 401.
2. **Authorize scope** — for routes that name a `tenant_id`/`user_id` in the query
   string, the values must match the authenticated principal, or 403. Body routes
   (chat, retention) enforce the same match in-route via `enforce_scope`, which
   reads the principal this middleware attaches.

The middleware never reads the request body (avoids ASGI body-replay fragility) and
never raises for server reasons — an auth failure is a 401/403, not a 500.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .principal import Principal
from .providers import build_provider

# `/api/*` paths that carry no tenant/user and need no authenticated caller.
# NOTE: /api/evals is intentionally NOT public — the on-demand run trigger is a
# compute-abuse vector, so when auth is enabled it is guarded like every other
# route, and even with auth off the route itself is gated by MEMORYOPS_PUBLIC_EVALS.
_PUBLIC_API_PATHS: frozenset[str] = frozenset()


def _guarded(path: str) -> bool:
    return path.startswith("/api/") and path not in _PUBLIC_API_PATHS


def install_auth_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def auth_scope(request: Request, call_next):
        from ..core.config import get_settings

        settings = get_settings()
        provider = build_provider(settings)
        if provider is None or not _guarded(request.url.path):
            return await call_next(request)

        principal = provider.resolve(request.headers)
        if principal is None:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "missing or invalid credentials",
                    "trace_id": getattr(request.state, "trace_id", "-"),
                },
            )
        request.state.principal = principal

        # Authorize any tenant/user named in the query string.
        q = request.query_params
        mismatch = _scope_mismatch(principal, q.get("tenant_id"), q.get("user_id"))
        if mismatch:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": f"request scope does not match authenticated principal ({mismatch})",
                    "trace_id": getattr(request.state, "trace_id", "-"),
                },
            )
        return await call_next(request)


def _scope_mismatch(principal: Principal, tenant_id: str | None, user_id: str | None) -> str | None:
    if tenant_id is not None and tenant_id != principal.tenant_id:
        return "tenant_id"
    if user_id is not None and user_id != principal.user_id:
        return "user_id"
    return None
