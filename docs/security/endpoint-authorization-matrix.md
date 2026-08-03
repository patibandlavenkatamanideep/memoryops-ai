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

Role resolution has **three** states, not two:

| Credential | Result |
| --- | --- |
| claim **omitted**, `auth_require_role_claim=false` | falls back to `memory_reader` |
| claim **omitted**, `auth_require_role_claim=true` (production) | **no permissions** |
| claim names recognised roles | those roles |
| claim present but names nothing recognised | **no permissions** |
| claim present but **empty** (`[]`, `""`) | **no permissions** |

An omitted claim is a *compatibility* question the deployment answers. An empty
claim is an *authorization decision the issuer already made* — a credential the IdP
deliberately granted no roles must receive nothing, not the fallback.

The last row matters: collapsing it into `memory_reader` would mean
`roles=["service_workre"]` — a typo — silently receives `memory:read:self` and
`memory:write:self`. A mistyped credential must grant nothing.

An issuer sending `"admin"` cannot accidentally match `tenant_admin`.

`is_service_account` comes from an explicit `actor_type` claim
(`MEMORYOPS_AUTH_JWT_ACTOR_TYPE_CLAIM`) or `X-MemoryOps-Actor-Type` header — never
inferred from a role name.

## Enforced today

These routes check a permission at the route boundary. Everything else is listed
under *Planned* below — this table states what the runtime does, not what the model
could express.

| Endpoint | Method | Permission | Scope |
| --- | --- | --- | --- |
| `/api/audit` (scoped) | GET | `audit:read:self` | forced to caller's `user_id` |
| `/api/audit` (tenant-wide) | GET | **`audit:read:tenant`** | tenant |
| `/api/metrics` | GET | **`metrics:read:tenant`** | tenant |
| `/api/admin/workers/health` | GET | **`worker:read`** | full detail |
| `/healthz` | GET | none — public | process liveness only |
| `/healthz/workers` | GET | none — public | **`{"healthy": …}` only** |

Every route also remains tenant-scoped by the existing middleware and
`enforce_scope`, which is unchanged.

## Planned — route coverage not yet enforced

The permission vocabulary exists and these are the intended assignments, but the
routes do **not** yet check them. Do not rely on this section as a control.

| Endpoint | Method | Intended permission |
| --- | --- | --- |
| `/api/chat` | POST | `memory:write:self` |
| `/api/memories`, `/api/memories/{id}` | GET | `memory:read:self` |
| `/api/memories/{id}` content/importance/confidence | PATCH | `memory:write:self` |
| `/api/memories/{id}` pending→active | PATCH | `memory:approve` |
| `/api/memories/{id}` archive/restore | PATCH | `memory:archive` |
| `/api/memories/{id}` | DELETE | `memory:delete` |
| `/api/retention/*` read | GET | `retention:read` |
| `/api/retention/*` mutation, legal hold | POST | `retention:manage` |
| `/api/retention/consent` | POST | `consent:manage` |
| `/api/evidence/*` | GET | `evidence:read` |
| `/api/traces` | GET | `traces:read:tenant` |
| `/api/evals/run` | POST | `evals:run` |

Tracked in `feat/api-rbac-route-coverage`, together with a CI guard that enumerates
sensitive routes from the FastAPI router and fails when one declares no
authorization requirement — so this table cannot drift from the runtime again.

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
identifiers of every scope the fleet had processed.

It now returns `{"healthy": …}` and nothing else. Run counts, dead-letter and
failure totals, per-scope history and failure reasons all moved to
`/api/admin/workers/health` behind `worker:read` — aggregate counts still disclose
deployment activity and operational condition to an unauthenticated caller.

## Behaviour when auth is disabled

`MEMORYOPS_AUTH_MODE=none` produces no principal, and authorization is a no-op —
the same contract as `enforce_scope`. That keeps the zero-infra demo and the offline
test suite working, and is safe because `MEMORYOPS_PROFILE=production` refuses to
start with auth disabled.

## Limitation

MemoryOps provides API authorization enforcement and adapter patterns. **It does not
replace an identity provider.** Roles arrive as claims from whatever issuer you
already run; MemoryOps verifies and enforces them, it does not issue them.
