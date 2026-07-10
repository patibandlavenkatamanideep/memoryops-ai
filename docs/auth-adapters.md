# Auth + authorization adapters

MemoryOps is **identity-neutral**. It is not an auth product and does not issue or
store credentials — it *verifies* an identity your issuer already minted, and then
enforces that every memory operation is scoped to that authenticated tenant/user
(v1.6, [ADR-020](../infra/adr/ADR-020-auth-authorization-adapters.md)).

Before v1.6 MemoryOps trusted `tenant_id`/`user_id` from the request. That is fine
behind a trusted internal boundary, but to run behind real user identity you turn on
one of two modes. **Both are off by default** (`auth_mode="none"`), so nothing
changes until you opt in.

## Modes

| `MEMORYOPS_AUTH_MODE` | How identity arrives | Use when |
| --- | --- | --- |
| `none` (default) | trusts the body, as before | internal / trusted network |
| `trusted_header` | an authenticated upstream injects `X-MemoryOps-Tenant` / `X-MemoryOps-User` | you already terminate auth at a gateway/BFF (**bring-your-own-auth**) |
| `jwt` | MemoryOps verifies `Authorization: Bearer <jwt>` and maps claims | you want MemoryOps to verify tokens directly |

Whatever the mode, enforcement is the same: the `tenant_id`/`user_id` a request
carries (query string or JSON body) **must match the authenticated principal**, or the
call is rejected — `401` for a missing/invalid credential, `403` for a scope mismatch.

## What is enforced where

- The **scope-validation middleware** (`app/auth/middleware.py`) authenticates every
  `/api/*` request and checks any `tenant_id`/`user_id` in the **query string**.
- Body routes (`POST /api/chat`, `POST /api/retention/*`) call `enforce_scope()`
  after the body is parsed, so a caller can never name another tenant in the body.
- The check never reads the body in the middleware (no ASGI body-replay fragility)
  and never raises a `500` — an auth failure is always a clean `401`/`403`.

## Bring-your-own-auth (`trusted_header`)

Terminate auth wherever you already do (Clerk/Auth0/Supabase edge, an API gateway,
your own backend-for-frontend), then forward the verified identity as headers:

```bash
export MEMORYOPS_AUTH_MODE=trusted_header
# defaults shown; override if your proxy uses different header names
export MEMORYOPS_AUTH_TENANT_HEADER=X-MemoryOps-Tenant
export MEMORYOPS_AUTH_USER_HEADER=X-MemoryOps-User
```

> Only expose MemoryOps *behind* that proxy — a client that can set these headers
> directly can impersonate. `trusted_header` trusts the network boundary by design.

## JWT verification (`jwt`)

MemoryOps verifies the token itself. HS256/384/512 need only the standard library;
RS256/384/512 additionally need the `cryptography` package (pass the PEM public key as
the key).

```bash
export MEMORYOPS_AUTH_MODE=jwt
export MEMORYOPS_AUTH_JWT_KEY='<shared secret or PEM public key>'
export MEMORYOPS_AUTH_JWT_ALGORITHMS=HS256          # comma-separated allow-list
export MEMORYOPS_AUTH_JWT_USER_CLAIM=sub             # which claim is the user id
export MEMORYOPS_AUTH_JWT_TENANT_CLAIM=tenant_id     # dotted path ok (nested claims)
export MEMORYOPS_AUTH_JWT_AUDIENCE=memoryops         # optional, verified if set
export MEMORYOPS_AUTH_JWT_ISSUER=https://issuer/      # optional, verified if set
```

`exp` / `nbf` are always enforced (60s leeway); `aud` / `iss` are enforced when set.

### Clerk

Clerk session JWTs carry `sub` (the user) and, for organizations, `org_id`. Map the
tenant to the org (or a custom claim you add in the JWT template):

```bash
export MEMORYOPS_AUTH_MODE=jwt
export MEMORYOPS_AUTH_JWT_ALGORITHMS=RS256
export MEMORYOPS_AUTH_JWT_KEY="$(cat clerk_jwks_public.pem)"   # from your Clerk JWKS
export MEMORYOPS_AUTH_JWT_USER_CLAIM=sub
export MEMORYOPS_AUTH_JWT_TENANT_CLAIM=org_id                  # or a custom "tenant" claim
export MEMORYOPS_AUTH_JWT_ISSUER=https://<your-app>.clerk.accounts.dev
```

### Auth0

Auth0 access tokens use `sub` for the user; put the tenant in a namespaced custom
claim via an Auth0 Action (`https://memoryops/tenant`):

```bash
export MEMORYOPS_AUTH_MODE=jwt
export MEMORYOPS_AUTH_JWT_ALGORITHMS=RS256
export MEMORYOPS_AUTH_JWT_KEY="$(cat auth0_public.pem)"
export MEMORYOPS_AUTH_JWT_USER_CLAIM=sub
export MEMORYOPS_AUTH_JWT_TENANT_CLAIM='https://memoryops/tenant'
export MEMORYOPS_AUTH_JWT_AUDIENCE=https://api.memoryops
export MEMORYOPS_AUTH_JWT_ISSUER=https://<tenant>.us.auth0.com/
```

### Supabase

Supabase issues HS256 JWTs signed with your project's JWT secret; `sub` is the user
and the tenant typically lives in `app_metadata`:

```bash
export MEMORYOPS_AUTH_MODE=jwt
export MEMORYOPS_AUTH_JWT_ALGORITHMS=HS256
export MEMORYOPS_AUTH_JWT_KEY='<supabase project JWT secret>'
export MEMORYOPS_AUTH_JWT_USER_CLAIM=sub
export MEMORYOPS_AUTH_JWT_TENANT_CLAIM=app_metadata.tenant_id   # nested claim
export MEMORYOPS_AUTH_JWT_ISSUER=https://<project>.supabase.co/auth/v1
```

## Verifying it works

```bash
# 401 without a credential, 200 with a matching one, 403 across tenants:
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/api/chat \
  -H 'content-type: application/json' \
  -d '{"tenant_id":"t1","user_id":"u1","message":"hi"}'                  # 401

curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/api/chat \
  -H 'content-type: application/json' -H 'X-MemoryOps-Tenant: t1' -H 'X-MemoryOps-User: u1' \
  -d '{"tenant_id":"t1","user_id":"u1","message":"hi"}'                  # 200
```

## Limits

- MemoryOps does not manage sessions, refresh, revocation lists, or JWKS rotation —
  your issuer owns those. For `jwt` mode with rotating keys, front MemoryOps with a
  proxy that validates against live JWKS and switch to `trusted_header`, or supply the
  current public key.
- This is transport-level authorization of *who* may act on a tenant. It is
  orthogonal to the [Context Admission Gate](context-admission-gate.md), which governs
  *which memories* enter a prompt for an already-authorized caller.
