# ADR-020 — Auth + Authorization Adapters

- Status: Accepted (v1.6)
- Date: 2026-07-09
- Supersedes: none
- Related: ADR-006 (RLS / tenant isolation), ADR-017 (admission gate), ADR-013
  (governance)

## Context

Tenant isolation (invariant #1) is enforced end-to-end in the data layer — every
query filters by `tenant_id` + `user_id`, and Postgres RLS `FORCE`s it (ADR-006). But
those identifiers arrive **from the caller**. That is correct for infrastructure sitting
behind a trusted boundary, yet to run behind real user identity MemoryOps needs a clear,
standard way to (a) verify *who* the caller is and (b) prove the request cannot act
outside its own tenant/user. We explicitly do **not** want to build an auth product
(sessions, refresh, user store) — that duplicates Clerk/Auth0/Supabase and expands the
trust surface.

## Decision

Add an **identity-neutral** auth layer (`app/auth/`) that verifies an externally-minted
identity and enforces request scoping. It is **off by default** (`auth_mode="none"`),
so existing deployments are unchanged.

- **Two modes.** `trusted_header` reads `X-MemoryOps-Tenant` / `X-MemoryOps-User`
  injected by an authenticated upstream (the bring-your-own-auth pattern). `jwt`
  verifies an `Authorization: Bearer` token and maps configured claims
  (`tenant_claim` / `user_claim`, dotted paths allowed) to the principal.
- **Dependency-free JWT** (`app/auth/jwt.py`). HS256/384/512 use the stdlib `hmac`, so
  the default path adds no dependency and tests need no keys. RS256/384/512 work *iff*
  `cryptography` is installed (PEM public key). `exp`/`nbf` always checked; `aud`/`iss`
  when configured. Any failure raises `JWTError`, mapped to 401 — never a 500.
- **Scope-validation middleware** (`app/auth/middleware.py`). Authenticates every
  `/api/*` request and validates any `tenant_id`/`user_id` in the **query string**
  against the principal. It never reads the request body (avoids ASGI body-replay
  fragility) and is installed *inside* `request_context` so trace_id + metrics still
  wrap a 401/403.
- **In-route enforcement for body routes.** `enforce_scope(request, tenant, user)` is
  called by `POST /api/chat` and `POST /api/retention/*` after the body is parsed, so
  a caller cannot name another tenant in the body. It is a no-op when auth is off.
- **Adapters as documentation, not code.** Clerk / Auth0 / Supabase / BYO are all the
  same two mechanisms with different claim mappings and issuers; `docs/auth-adapters.md`
  gives copy-paste env for each rather than a bespoke SDK per provider.

## Consequences

- MemoryOps can sit behind real identity without owning identity: verify + scope, then
  hand off to the existing tenant-scoped repository and admission gate.
- Defense-in-depth: authorization is now enforced at the transport edge *and* the data
  layer (RLS). A scope mismatch is rejected before the store is touched.
- Additive + backward compatible: default `none` changes no behavior; all existing
  tests pass unchanged. New knobs are `MEMORYOPS_AUTH_*`.
- Cost is one header/JWT check per request when enabled; verification is O(token size).

## Out of scope (later)

- Session/refresh/revocation, live JWKS rotation, and per-route RBAC beyond
  tenant/user scoping (front with a proxy or extend the provider).
- Signing/minting tokens — MemoryOps only ever *verifies*.
- Fine-grained per-memory ACLs / audience-aware disclosure — that is the Recall/Output
  Gate direction (v1.9).
