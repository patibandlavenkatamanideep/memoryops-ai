# Railway environment variables

Every variable consumed by MemoryOps AI, per service. Settings are typed in
[`services/api/app/core/config.py`](../../services/api/app/core/config.py)
(`env_prefix=""`, so each field maps to its **UPPERCASE** name) plus the
explicit `MEMORYOPS_*` aliases resolved in `get_settings()`.

`DATABASE_URL` and `REDIS_URL` are provided automatically when you reference the
Railway Postgres / Redis plugins — use Railway's **variable references** rather
than copying values.

## `memoryops-api`

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `PORT` | auto | — | Injected by Railway; bind uvicorn to it. |
| `MEMORYOPS_STORAGE` | ✅ | `memory` | Set to `postgres` in production. |
| `DATABASE_URL` | ✅ (postgres) | local dsn | `postgresql+psycopg://…`. Reference the Postgres plugin. |
| `REDIS_URL` | ✅ | `redis://localhost:6379/0` | Reference the Redis plugin. |
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

| Variable | Required | Notes |
|----------|----------|-------|
| `PORT` | auto | Injected by Railway. |
| `NEXT_PUBLIC_API_URL` | ✅ | Public URL of `memoryops-api`. **Build-time** — inlined by Next.js; a change requires a rebuild. |
| `NODE_ENV` | — | `production` (set in the image). |

## `memoryops-worker`

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `MEMORYOPS_STORAGE` | ✅ | `memory` | Set to `postgres` to share the API store. |
| `DATABASE_URL` | ✅ (postgres) | local dsn | Reference the Postgres plugin. |
| `REDIS_URL` | ✅ | `redis://localhost:6379/0` | Reference the Redis plugin. |
| `WORKER_INTERVAL_SECONDS` | — | `60` | Scheduler tick interval. |

## Railway Postgres plugin

Provides `DATABASE_URL` (and `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`).
MemoryOps uses `DATABASE_URL` with the `postgresql+psycopg://` driver prefix —
if the plugin emits a bare `postgres://`, set `DATABASE_URL` explicitly with the
`+psycopg` prefix. Enable the `vector` extension and apply
`infra/db/migrations/001…005` in order.

## Railway Redis plugin

Provides `REDIS_URL`. Used for queue/cache; the worker and API both reference it.

## Minimum production set

The smallest working production config:

```
# api + worker
MEMORYOPS_STORAGE=postgres
DATABASE_URL=<reference Postgres plugin, +psycopg prefix>
REDIS_URL=<reference Redis plugin>

# web
NEXT_PUBLIC_API_URL=https://memoryops-api.up.railway.app
```

Everything else has a safe default, and the system stays fully functional with
**no provider API keys** (heuristic LLM + stub embeddings, invariant #4).
