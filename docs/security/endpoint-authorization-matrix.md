# Endpoint authorization matrix

Which permission each API surface requires. Enforced **in the API**, not in the web
tier — a caller talking to the API directly bypasses every BFF role check.

Generated behaviour is asserted in `services/api/tests/test_api_rbac.py`.

## Roles

| Role | Intent |
| --- | --- |
| `memory_reader` | Read and write **their own** memory. The default for an authenticated caller with no recognised role claim. |
| `memory_admin` | Manage memory across the tenant: approve, archive, delete, retention, consent. |
| `auditor` | Read governance evidence tenant-wide. **Cannot mutate memory** — an auditor who can edit what they audit is not an auditor. |
| `tenant_admin` | Every permission, within one tenant. |
| `service_worker` | Machine identity for the worker fleet: operational reads and replay only, never memory content. |

An authenticated caller with **no recognised role** falls back to `memory_reader`.
Unrecognised names are ignored rather than trusted, so an issuer sending `"admin"`
cannot accidentally match `tenant_admin`, and a typo cannot escalate.

## Matrix

| Endpoint | Method | Permission | Scope |
| --- | --- | --- | --- |
| `/api/chat` | POST | `memory:write:self` | own user |
| `/api/memories` | GET | `memory:read:self` | own user |
| `/api/memories/{id}` | PATCH | `memory:write:self` (+ `memory:approve` / `memory:archive` for transitions) | own user |
| `/api/memories/{id}` | DELETE | `memory:delete` | own user |
| `/api/audit` (scoped) | GET | `audit:read:self` | forced to caller's `user_id` |
| `/api/audit` (tenant-wide) | GET | **`audit:read:tenant`** | tenant |
| `/api/metrics` | GET | **`metrics:read:tenant`** | tenant |
| `/api/traces` | GET | `traces:read:tenant` | tenant |
| `/api/retention/*` | POST | `retention:manage` / `consent:manage` | tenant |
| `/api/evidence/*` | GET | `evidence:read` | tenant |
| `/api/evals/run` | POST | `evals:run` | tenant |
| `/healthz` | GET | none — public | process liveness only |
| `/healthz/workers` | GET | none — public | **safe aggregate only** |
| `/api/admin/workers/health` | GET | **`worker:read`** | full detail |

## The two holes this closed

**Tenant-wide audit.** `/api/audit` took `tenant_id` from the query string with
`user_id` optional, and applied no authorization. The scope-validation middleware
only checks a `user_id` that is *present*, so omitting it skipped validation and the
route returned tenant-wide records. Reproduced with auth on:

```
alice GET /api/audit?tenant_id=acme   -> 200
audit rows returned for users: {'alice', 'bob'}
```

A tenant-wide read now requires `audit:read:tenant`; without it the query is forced
to the caller's own `user_id`.

**Worker health.** `/healthz/workers` sits **outside** the `/api/*` authentication
boundary, so it is reachable unauthenticated. It returned `last_run_per_scope`,
whose keys are built as `f"{tenant_id}:{user_id}"` — leaking the tenant and user
identifiers of every scope the fleet had processed. It now returns counts only; the
detailed view moved to `/api/admin/workers/health` behind `worker:read`.

## Behaviour when auth is disabled

`MEMORYOPS_AUTH_MODE=none` produces no principal, and authorization is a no-op —
the same contract as `enforce_scope`. That keeps the zero-infra demo and the offline
test suite working, and is safe because `MEMORYOPS_PROFILE=production` refuses to
start with auth disabled.

## Limitation

MemoryOps provides API authorization enforcement and adapter patterns. **It does not
replace an identity provider.** Roles arrive as claims from whatever issuer you
already run; MemoryOps verifies and enforces them, it does not issue them.
