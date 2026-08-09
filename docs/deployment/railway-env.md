# Railway environment variables

Every variable consumed by MemoryOps AI, per service. Settings are typed in
[`services/api/app/core/config.py`](../../services/api/app/core/config.py)
(`env_prefix=""`, so each field maps to its **UPPERCASE** name) plus the
explicit `MEMORYOPS_*` aliases resolved in `get_settings()`.

`DATABASE_URL` is provided automatically when you reference the Railway Postgres
plugin — use Railway's **variable references** rather than copying values.

> Redis is no longer part of the topology: `REDIS_URL` was declared and health-gated
> but never read by any runtime code. See [railway.md](railway.md).

## `memoryops-api`

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `PORT` | auto | — | Injected by Railway; bind uvicorn to it. |
| `MEMORYOPS_STORAGE` | ✅ | `memory` | Set to `postgres` in production. |
| `DATABASE_URL` | ✅ (postgres) | local dsn | `postgresql+psycopg://…`. Reference the Postgres plugin. |
| `MEMORYOPS_PROFILE` | ✅ (prod) | `dev` | Set to `production`; fail-closed startup checks. |
| `MEMORYOPS_AUTH_MODE` | ✅ (prod) | `none` | `jwt` or `trusted_header`; `none` is rejected in production. |
| `MEMORYOPS_AUTH_JWT_KEY` | ✅ (prod, **secret**) | *(empty)* | HS\* signing key (or RS\* public key). **Must be byte-identical to the web service's value** — the web BFF signs tokens the API verifies. Not validated at startup: with `auth_mode=jwt` and no key the API boots and then rejects every credential with 401. |
| `MEMORYOPS_AUTH_REQUIRE_ROLE_CLAIM` | ✅ (prod) | `false` | Set `true`. A credential with no roles claim then gets **no** permissions instead of falling back to `memory_user`. The production profile **refuses to start** without it. |
| `MEMORYOPS_PROTECT_METRICS_ENDPOINT` | ✅ (prod) | `false` | Set `true` on any deployment where `/metrics` is reachable from the public internet; requires `ops:metrics`. The default is safe only behind private networking — a Railway public hostname is not that. |
| `MEMORYOPS_CORS_ALLOW_ORIGINS` | ✅ (prod) | `*` | Explicit origin list; `*` is rejected in production. Note the name: `MEMORYOPS_CORS_ORIGINS` is **not** read. |
| `MEMORYOPS_PUBLIC_EVALS` | ✅ (prod) | `false` | Must stay `false` (denial-of-wallet vector). |
| `OPERATIONAL_DATABASE_URL` | ✅ (prod, **secret**) | *(unset)* | Restricted monitoring role — see [Operational monitoring role](#operational-monitoring-role). Required for MemoryOps' production profile: without it `/healthz/workers` reports `{"healthy": false}` and the release smoke gate fails C1. |
| `LLM_PROVIDER` | — | `heuristic` | `heuristic` needs no keys (v0.3.x). `openai`/`anthropic`/`gemini` land in v0.4. |
| `MEMORYOPS_EMBEDDING_PROVIDER` | — | `stub` | `stub` is deterministic/offline; `openai` needs a key. |
| `EMBEDDING_DIM` | — | `1536` | Must match the pgvector column dimension. |
| `OPENAI_EMBEDDING_MODEL` | — | `text-embedding-3-small` | Only when embeddings provider = `openai`. |
| `LOG_LEVEL` | — | `INFO` | |
| `SERVICE_NAME` | — | `memoryops-api` | |

### Optional provider keys (used only when present)

| Variable | Notes |
|----------|-------|
| `OPENAI_API_KEY` | Enables OpenAI embeddings now; OpenAI LLM adapter in v0.4. |
| `ANTHROPIC_API_KEY` | Reserved for the v0.4 Anthropic adapter. |
| `GEMINI_API_KEY` | Reserved for the v0.4 Gemini adapter. |

### Headroom context compression (optional, ADR-007)

| Variable | Default | Notes |
|----------|---------|-------|
| `MEMORYOPS_CONTEXT_COMPRESSION` | `none` | `none` is transparent; `headroom` uses the optional adapter and degrades to no-op on failure. |
| `MEMORYOPS_COMPRESSION_REQUIRE_POLICY_CLEARED` | `true` | Compression only runs after policy/governance/composition. |
| `HEADROOM_MODE` | `library` | `library` \| `proxy` \| `mcp`. |
| `HEADROOM_OUTPUT_SHAPER` | `false` | |

### Reliability knobs (optional)

| Variable | Default |
|----------|---------|
| `LLM_TIMEOUT_SECONDS` | `8.0` |
| `RETRIEVAL_TIMEOUT_SECONDS` | `3.0` |
| `CIRCUIT_BREAKER_THRESHOLD` | `5` |
| `CIRCUIT_BREAKER_RESET_SECONDS` | `30.0` |

## `memoryops-web`

The authenticated control plane. The browser never holds an API credential: the
Next.js BFF resolves identity server-side and mints a short-lived HS256 token per
request (`apps/web/lib/memoryopsToken.ts`).

**Classification:** 🔒 secret · ✅ required in production · ○ optional · 🌐 public/build-time

| Variable | Class | Default | Notes |
|----------|-------|---------|-------|
| `PORT` | auto | — | Injected by Railway. |
| `MEMORYOPS_WEB_MODE` | ✅ | `demo` | Must be `authenticated` in production. Deliberately **not** `NEXT_PUBLIC_*` — authorization must never be decided by a value the browser can read. Unset throws at request time in production. |
| `AUTH_SECRET` | 🔒 ✅ | — | Auth.js (NextAuth v5) session-signing secret, read implicitly by the framework. **Not the same value as `MEMORYOPS_AUTH_JWT_KEY`** — generate it separately. |
| `AUTH_TRUST_HOST` | ✅ | — | Set `true`. Railway terminates TLS at a reverse proxy, and Auth.js will not trust the forwarded host without it, so callback URLs break. |
| `MEMORYOPS_WEB_OPERATORS` | 🔒 ✅ | *(empty)* | Sign-in records for the built-in Credentials provider — see [format](#memoryops_web_operators-format). Replace this provider with a real IdP for anything beyond a controlled deployment. |
| `MEMORYOPS_AUTH_MODE` | ✅ | `none` | Mirror the API: `jwt`. Demo web mode combined with an authenticating API mode fails closed rather than minting a shared admin credential. |
| `MEMORYOPS_AUTH_JWT_KEY` | 🔒 ✅ | *(empty)* | **Byte-identical to the API's value.** The BFF signs with it; the API verifies with it. If they differ the API rejects every BFF call while both services look healthy. |
| `MEMORYOPS_API_URL` | ✅ | `http://localhost:8000` | Server-only upstream API base URL. Preferred over `NEXT_PUBLIC_API_URL` for the BFF hop so no API address needs to be public. |
| `NEXT_PUBLIC_API_URL` | 🌐 ✅ | — | Public URL of `memoryops-api`. **Build-time** — inlined by Next.js; a change requires a rebuild, not a restart. |
| `MEMORYOPS_API_TOKEN_TTL_SECONDS` | ○ | `120` | Lifetime of the minted API token. Short by design: it only has to survive one server-to-server hop. |
| `MEMORYOPS_AUTH_JWT_AUDIENCE` / `..._ISSUER` | ○ | *(empty)* | Set only if the API also sets them; the values must match. |
| `NODE_ENV` | — | `production` | Set in the image. |

### Sharing the JWT key between API and web

Define it **once** as a Railway project-level shared variable and reference it from
both services, so the two cannot drift:

```
MEMORYOPS_AUTH_JWT_KEY=${{ shared.MEMORYOPS_AUTH_JWT_KEY }}
```

### `MEMORYOPS_WEB_OPERATORS` format

Comma-separated `tenant:user:role:password` records, parsed in `apps/web/auth.ts`:

```
MEMORYOPS_WEB_OPERATORS=<tenant>:<user>:<web-role>:<password>,<tenant>:<user>:<web-role>:<password>
```

`<web-role>` is a **web persona**, not an API role. The five valid personas and the
API role each maps to (`contracts/auth-role-map.json`):

| Web persona | API role |
|-------------|----------|
| `viewer` | `memory_viewer` |
| `developer` | `memory_user` |
| `auditor` | `auditor` |
| `memory_admin` | `memory_admin` |
| `owner` | `tenant_admin` |

`service_worker` and `platform_operator` are in `never_web_assignable` — no UI
session may become deployment authority.

> Passwords here are credentials. Keep them in Railway's variable store (sealed if
> you can, having saved the value elsewhere first — a sealed variable cannot be read
> back), never in the repository, a ticket, or a chat.

## `memoryops-worker`

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `MEMORYOPS_STORAGE` | ✅ | `memory` | Set to `postgres` to share the API store. |
| `DATABASE_URL` | ✅ (postgres) | local dsn | Reference the Postgres plugin. |
| `MEMORYOPS_WORKER_SCOPES` | ✅ | `tenant_demo:user_demo` | `"tenant:user,…"` scopes to process. |
| `WORKER_INTERVAL_SECONDS` | — | `60` | Scheduler tick interval. |

## Operational monitoring role

Global worker health has to be observable **without** granting access to tenant
memory. The request-scoped connection is RLS-enforced and deliberately cannot see
across tenants, so aggregating worker runs through it is impossible by design.
`OPERATIONAL_DATABASE_URL` is a second, separately authorized connection used only
for operator views.

It is **fail-closed**: unset, MemoryOps does not silently fall back to the
application connection. It reports that operational access is unavailable.

### Expected behaviour when it is unset

| Endpoint | Response |
|----------|----------|
| `GET /healthz/workers` (public) | `{"healthy": false}` — liveness only, never scope keys |
| `GET /api/admin/workers/health` (`worker:read`) | `{"healthy": null, "detail": "operational access not configured", "hint": "set OPERATIONAL_DATABASE_URL to a monitoring role"}` |

`healthy: false` here means *"worker health is not observable"*, which is not the
same as *"the worker is broken"* — but the release gate cannot tell those apart, and
neither can an operator. `scripts/release_smoke_v24.py` requires `healthy` to be
exactly `true`, so a deployment without this role fails C1.

### Creating `memoryops_monitor`

Least privilege: it may read worker run history and nothing else. `BYPASSRLS` is
required because the whole point is a cross-tenant aggregate; the `SELECT` grants are
what keep that from becoming cross-tenant *memory* access.

```sql
-- Replace the placeholder before running. Do not commit the real value.
CREATE ROLE memoryops_monitor LOGIN PASSWORD '<REPLACE_WITH_GENERATED_PASSWORD>' BYPASSRLS;

GRANT CONNECT ON DATABASE memoryops TO memoryops_monitor;
GRANT USAGE   ON SCHEMA public      TO memoryops_monitor;

-- Worker run history only.
GRANT SELECT ON worker_runs TO memoryops_monitor;

-- Explicitly NOT granted: memory_records, audit_events, or any tenant-content table.
-- Verify the boundary holds (both should error):
--   SET ROLE memoryops_monitor; SELECT count(*) FROM memory_records;
```

Then point the variable at that role — **not** at the application role:

```
OPERATIONAL_DATABASE_URL=postgresql+psycopg://memoryops_monitor:<password>@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}
```

> Do not widen these grants to make a dashboard easier. A monitoring role that can
> read `memory_records` is a cross-tenant read path that bypasses RLS by design, which
> is precisely what the split connection exists to prevent.

## Railway Postgres plugin

Provides `DATABASE_URL` (and `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`).
MemoryOps uses `DATABASE_URL` with the `postgresql+psycopg://` driver prefix —
if the plugin emits a bare `postgres://`, set `DATABASE_URL` explicitly with the
`+psycopg` prefix. Enable the `vector` extension, then apply **every** file in
`infra/db/migrations` in lexical order:

```bash
for f in infra/db/migrations/*.sql; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
```

Do not hand-maintain a migration range here. This page previously said `001…005`
and the deployment guide said `001…007`, while the repository had migrations
through `011` — two different stale answers, both producing an incomplete schema.

## Minimum production set

`MEMORYOPS_PROFILE=production` is fail-closed, so this is the smallest config that
actually **boots**. The previous version of this list omitted the profile, auth,
CORS, and evals variables that the profile itself requires.

```
# api
MEMORYOPS_PROFILE=production
MEMORYOPS_STORAGE=postgres
MEMORYOPS_AUTH_MODE=jwt                       # or trusted_header
MEMORYOPS_AUTH_JWT_KEY=${{ shared.MEMORYOPS_AUTH_JWT_KEY }}
MEMORYOPS_AUTH_REQUIRE_ROLE_CLAIM=true        # profile refuses to start without it
MEMORYOPS_PROTECT_METRICS_ENDPOINT=true       # /metrics is public on Railway otherwise
MEMORYOPS_CORS_ALLOW_ORIGINS=https://memoryops-web.up.railway.app
MEMORYOPS_PUBLIC_EVALS=false
DATABASE_URL=<reference Postgres plugin, +psycopg prefix>
OPERATIONAL_DATABASE_URL=<memoryops_monitor role, +psycopg prefix>

# worker
MEMORYOPS_PROFILE=production
MEMORYOPS_STORAGE=postgres
DATABASE_URL=<reference Postgres plugin, +psycopg prefix>
MEMORYOPS_WORKER_SCOPES=<tenant:user,…>       # without it the worker idles, healthily

# web
MEMORYOPS_WEB_MODE=authenticated
AUTH_SECRET=<generated; NOT the JWT key>
AUTH_TRUST_HOST=true                          # Railway terminates TLS at a proxy
MEMORYOPS_WEB_OPERATORS=<tenant:user:role:password,…>
MEMORYOPS_AUTH_MODE=jwt
MEMORYOPS_AUTH_JWT_KEY=${{ shared.MEMORYOPS_AUTH_JWT_KEY }}   # same value as the API
MEMORYOPS_API_URL=https://memoryops-api.up.railway.app
NEXT_PUBLIC_API_URL=https://memoryops-api.up.railway.app      # build-time
```

The four most common ways this configuration fails, none of which announce
themselves:

1. **JWT key differs between API and web** — the API rejects every BFF call while
   both services report healthy.
2. **`MEMORYOPS_AUTH_JWT_KEY` unset on the API** — boots fine, then 401s everything;
   nothing validates it at startup.
3. **`MEMORYOPS_WORKER_SCOPES` unset** — the worker starts, reports healthy, and
   processes nothing.
4. **`MEMORYOPS_CORS_ORIGINS` used instead of `MEMORYOPS_CORS_ALLOW_ORIGINS`** — the
   real setting stays `*`, and the production profile refuses to boot (this one at
   least fails loudly).

Everything else has a safe default, and the system stays fully functional with
**no provider API keys** (heuristic LLM + stub embeddings, invariant #4).
