# API RBAC

Authentication answers *who are you?*. Until this change nothing answered *may you
do this?*

`Principal` carried `tenant_id`, `user_id`, `provider` and `claims` — no role, no
permission. The web control plane added role checks, but they live in the Next.js
BFF, so a caller talking to the API directly bypassed all of them.

**Security cannot live only in the web tier.**

## What was reproduced

With authentication **on** (`MEMORYOPS_AUTH_MODE=trusted_header`):

```
alice GET /api/audit?tenant_id=acme        -> 200
  audit rows returned for users: {'alice', 'bob'}
alice GET /api/metrics?tenant_id=acme      -> 200  (tenant-wide counts)
GET /healthz/workers  (no credential)      -> 200  last_run_per_scope: {"acme:alice": …}
```

An ordinary authenticated user read another user's audit trail, tenant-wide metrics,
and — unauthenticated — the tenant/user identifiers of every worker scope.

## Model

Three pieces, deliberately small:

- **`Permission`** — what a caller may do (`audit:read:tenant`, `worker:read`, …).
  Routes check permissions, never roles.
- **`Role`** — a named bundle of permissions. Five of them. No hierarchy engine, no
  per-resource ACLs, no policy DSL.
- **`Principal`** — gains `roles`, `actor_id`, `is_service_account`, and derived
  `permissions`.

Because routes check *permissions*, adding a role can never implicitly grant access
to an endpoint that did not ask for its permission.

## Where roles come from

MemoryOps stays identity-neutral — roles are claims from your existing issuer.

| Mode | Source | Setting |
| --- | --- | --- |
| `jwt` | a claim in the verified token | `MEMORYOPS_AUTH_JWT_ROLES_CLAIM` (default `roles`, dotted paths allowed) |
| `trusted_header` | a header from the trusted proxy | `MEMORYOPS_AUTH_ROLES_HEADER` (default `X-MemoryOps-Roles`) |

Accepts a list, or a space/comma-separated string.

> **Trusted-header mode inherits its trust from the network.** The role header is as
> authoritative as the tenant/user headers already were: only safe when the API is
> private, the public edge strips inbound identity headers, and only the gateway can
> reach the API. If the API is publicly reachable, a caller can set these headers
> themselves. Use `jwt` mode when you cannot guarantee that.

## Defaults are least-privilege

An authenticated caller with no recognised role gets `memory_reader`: read and write
their **own** memory, read their **own** audit. Never a tenant-wide or administrative
default.

Unrecognised role names are dropped rather than trusted — an issuer sending `"admin"`
must not accidentally match `tenant_admin`.

## Behaviour change

This is a **security tightening**, and it will 403 callers that previously received
200 — specifically tenant-wide `/api/audit` and `/api/metrics` without an
auditor/admin role. That access should not have existed. The `1.x` additive promise
covers request/response *shape*; it does not promise that unauthorized access keeps
working.

Deployments with `MEMORYOPS_AUTH_MODE=none` are unaffected (no principal, no
enforcement) — and production already refuses to start in that mode.

## What this is not

MemoryOps provides API authorization enforcement and adapter patterns. It is **not**
an identity provider, and it does not implement SSO, SCIM, session revocation,
service-account issuance, or step-up authentication. Those remain your IdP's job and
are listed in `docs/limitations.md`.

See [endpoint-authorization-matrix.md](endpoint-authorization-matrix.md) for the
per-endpoint table.
