# ADR-028 — API-level RBAC and endpoint authorization

**Status:** accepted
**Supersedes nothing. Extends ADR-020 (auth adapters).**

## Context

ADR-020 added identity: MemoryOps verifies an externally-minted credential and
enforces that every operation is scoped to the authenticated tenant/user. It
answered *who are you?*

Nothing answered *may you do this?* `Principal` carried `tenant_id`, `user_id`,
`provider` and `claims` — no role, no permission, no scope.

The authenticated web control plane introduced role checks, but those live in the
Next.js BFF. A caller talking to the API directly bypasses them entirely. Hiding a
button is not authorization.

Reproduced with authentication on (`MEMORYOPS_AUTH_MODE=trusted_header`):

```
alice GET /api/audit?tenant_id=acme    -> 200, rows for {'alice', 'bob'}
alice GET /api/metrics?tenant_id=acme  -> 200, tenant-wide counts
GET  /healthz/workers  (no credential) -> 200, last_run_per_scope {"acme:alice": …}
```

Two distinct defects:

1. `/api/audit` took `tenant_id` from the query string with `user_id` **optional**
   and applied no authorization. The scope-validation middleware only checks a
   `user_id` that is *present*, so omitting it skipped validation and the route
   defaulted to tenant-wide.
2. `/healthz/workers` sits **outside** the `/api/*` authentication boundary and
   returned `last_run_per_scope`, whose keys are `f"{tenant_id}:{user_id}"`.

## Decision

Add a permission model to the API and enforce it at the route.

- `Permission` — the unit routes check. `Role` — a named bundle. `Principal` gains
  `roles`, `actor_id`, `is_service_account`, and derived `permissions`.
- Five roles: `memory_reader`, `memory_admin`, `auditor`, `tenant_admin`,
  `service_worker`. No hierarchy engine, no per-resource ACLs, no policy DSL.
- Routes check **permissions**, not roles, so adding a role cannot implicitly grant
  access to an endpoint that never asked for its permission.
- Roles arrive as claims (`MEMORYOPS_AUTH_JWT_ROLES_CLAIM`) or a trusted-proxy
  header (`MEMORYOPS_AUTH_ROLES_HEADER`). MemoryOps stays identity-neutral.
- Unrecognised role names are **dropped, not trusted**. An authenticated caller with
  no recognised role gets `memory_reader` — least privilege, never admin.
- `/healthz/workers` returns counts only. Detail moved to
  `/api/admin/workers/health` behind `worker:read`, inside the auth boundary.

### Why permissions rather than `require_roles(...)`

A role check hard-codes policy at the call site: `require_roles("auditor",
"tenant_admin")` has to be edited every time a role is added. A permission check
(`audit:read:tenant`) states what the endpoint *needs*, and the role table decides
who has it. The endpoint stays correct when the role set changes.

### Why authorization is a no-op when auth is disabled

Same contract as `enforce_scope`. `MEMORYOPS_AUTH_MODE=none` produces no principal
and no enforcement, which keeps the zero-infra demo and the offline test suite
working. Safe because `MEMORYOPS_PROFILE=production` already refuses to start with
auth disabled — so the permissive path cannot reach production.

## Consequences

**This is a behaviour change.** Tenant-wide `/api/audit` and `/api/metrics` now
return 403 without an auditor/admin role, where they previously returned 200. That
access should not have existed; the `1.x` additive promise covers request/response
shape, not continued unauthorized access.

`/healthz/workers` loses `last_run_per_scope`. Consumers needing it move to
`/api/admin/workers/health` with a `worker:read` credential.

**Trusted-header mode inherits its trust from the network.** The role header is
exactly as authoritative as the tenant/user headers already were — valid only when
the API is private, the public edge strips inbound identity headers, and only the
gateway can reach the API. Documented in `docs/security/api-rbac.md`; use `jwt` mode
where that cannot be guaranteed.

## Still open

Service-account issuance, scoped API keys, SSO/SCIM, session and token revocation,
and administrative step-up authentication remain out of scope — MemoryOps enforces
authorization, it does not issue identity. Per-resource ACLs and delegation are not
implemented. RLS remains tenant-level; user-level isolation is still enforced in
application SQL rather than by the database.
