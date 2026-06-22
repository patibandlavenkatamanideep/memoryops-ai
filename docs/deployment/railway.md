# Deploying MemoryOps AI on Railway

MemoryOps AI deploys to **Railway only**. There is no Vercel target and no
split-host topology — the frontend, backend, worker, database, and cache all live
in **one Railway project** as separate services. This keeps env wiring, private
networking, and the deploy story in a single place.

> Vercel is **not** a supported or recommended deployment path. If you see Vercel
> referenced anywhere, treat it as historical.

## Target architecture

**Railway project:** `memoryops-ai`

| # | Service | Role | Source | Health |
|---|---------|------|--------|--------|
| 1 | `memoryops-web` | Next.js frontend | `apps/web/Dockerfile` | `GET /` |
| 2 | `memoryops-api` | FastAPI backend | `services/api/Dockerfile` | `GET /healthz`, `GET /readyz` |
| 3 | `memoryops-worker` | Background jobs (decay/reflection/learning loop) | `services/worker/Dockerfile` | process liveness (no HTTP) |
| 4 | Railway **Postgres** | Primary store + pgvector | Railway plugin | managed |
| 5 | Railway **Redis** | Queue / cache | Railway plugin | managed |

All five run inside the same project so they share Railway's private network and
reference each other through Railway-provided variables (e.g. `DATABASE_URL`,
`REDIS_URL`). See [railway-env.md](railway-env.md) for the full variable matrix.

## Config-as-code

Each service ships a checked-in config file under [`railway/`](../../railway/):

- `railway/api.railway.json`
- `railway/web.railway.json`
- `railway/worker.railway.json`

Point each Railway service at its config file via **Service → Settings → Config
File** (config-as-code). Builder is `DOCKERFILE` for all three.

## Per-service settings

Set these in **Service → Settings** for each service. `dockerfilePath` in the
config files is resolved relative to the service **Root Directory**.

### 1. `memoryops-api`
- **Root Directory:** `services/api`
- **Config File:** `railway/api.railway.json`
- **Dockerfile path:** `Dockerfile` (relative to root)
- **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (from config)
- **Health check path:** `/healthz`
- Bind to `$PORT` — Railway injects it. Do **not** hardcode `8000` in production.

### 2. `memoryops-web`
- **Root Directory:** `apps/web`
- **Config File:** `railway/web.railway.json`
- **Dockerfile path:** `Dockerfile` (relative to root)
- **Start command:** `npm run start -- --port $PORT --hostname 0.0.0.0` (from config)
- **Health check path:** `/`
- `NEXT_PUBLIC_API_URL` must be set at **build time** to the public `memoryops-api`
  URL (Next.js inlines `NEXT_PUBLIC_*` at build).

### 3. `memoryops-worker`
- **Root Directory:** repo root (`/`) — the worker image copies `services/api`
  into the build, so its build context must be the repository root.
- **Config File:** `railway/worker.railway.json`
- **Dockerfile path:** `services/worker/Dockerfile` (relative to repo root)
- **Start command:** `python main.py` (from config)
- **No HTTP health check on the worker itself** — it is an interval scheduler, not
  a web server. As of v0.8 it runs the orchestrator + scheduler over the real
  lifecycle workers (leased, retried, dead-lettered); set
  `MEMORYOPS_WORKER_SCOPES="tenant:user,…"` and optionally
  `MEMORYOPS_WORKER_INTERVAL_SECONDS`. **Worker health is observable via the API**
  at `GET /healthz/workers` (run history, dead-letter / failure counts, last run
  per scope). See [worker-runtime.md](../worker-runtime.md).

## Deployment order

Provision and deploy in this order so dependencies are ready:

1. **Postgres** plugin — then run migrations from `infra/db/migrations` (apply
   `001…007` in order; `007_retention_legal_hold_consent.sql` is the latest).
2. **Redis** plugin.
3. **`memoryops-api`** — set `MEMORYOPS_STORAGE=postgres`, `DATABASE_URL`,
   `REDIS_URL`. Wait for `/readyz` to report `ready: true`.
4. **`memoryops-worker`** — same `DATABASE_URL` / `REDIS_URL` / `MEMORYOPS_STORAGE`.
5. **`memoryops-web`** — set `NEXT_PUBLIC_API_URL` to the public API domain, then
   deploy (build-time inline).

After all five are up, run the smoke test
([railway-smoke-test.md](railway-smoke-test.md)).

## Optional: Playground demo service (v0.12)

The public [Playground](../playground.md) (`apps/playground`) can be deployed as an
**optional** demo service — it is **not** one of the five core services. It needs
**no database and no secrets** (in-memory store + offline stubs), so it is safe to
host. Its Dockerfile copies `services/api`, so the Docker build context must be the
**repository root**:

- **Root Directory:** `/` (repo root) — **not** `apps/playground`.
- **Config File (config-as-code):** `railway/playground.railway.json` — this is what
  forces the **Dockerfile** builder; without it Railway falls back to Railpack at the
  repo root and the build fails ("Railpack could not determine how to build" /
  missing `start.sh`).
- **Builder / Dockerfile:** `DOCKERFILE`, `dockerfilePath: apps/playground/Dockerfile`
  (set in the config file).
- **Start command:** owned by the **Dockerfile `CMD`** (runs from the image
  `WORKDIR /app/apps/playground`):
  `sh -c "streamlit run streamlit_app.py --server.port ${PORT:-8501} --server.address 0.0.0.0 --server.headless true"`.
  Do **not** put this start command in `railway/playground.railway.json`: a
  config-as-code `startCommand` on a Dockerfile service runs in **exec form
  without shell expansion**, so Streamlit would receive the literal string
  `$PORT` and crash (healthcheck then fails). The Dockerfile `CMD` uses `sh -c`,
  so `${PORT:-8501}` expands correctly.
- **Health check:** `/_stcore/health` (Streamlit), `healthcheckTimeout: 300`.

## Health checks

- `memoryops-api`: Railway hits `healthcheckPath=/healthz` on the assigned `$PORT`.
  `/readyz` additionally touches the repository so a misconfigured DB surfaces as
  not-ready (useful for manual verification).
- `memoryops-web`: `/` returns 200 once Next.js is serving.
- `memoryops-worker`: no HTTP probe; Railway restarts on process exit
  (`restartPolicyType: ON_FAILURE`).

## Rollback

- Railway keeps prior deployments per service. To roll back, open the service →
  **Deployments** → pick the last-good deployment → **Redeploy**.
- Roll back **web** and **api** independently; they are decoupled by
  `NEXT_PUBLIC_API_URL`.
- Database migrations are **forward-only**. A rollback of the API does not revert
  schema; keep migrations additive (as `005_loop_engineering.sql` is) so an older
  API image still runs against a newer schema.

## Known limitations

- The API `Dockerfile` `HEALTHCHECK` hardcodes port `8000`; on Railway the
  platform health check uses `healthcheckPath` against `$PORT`, so the in-image
  `HEALTHCHECK` is cosmetic in production.
- `NEXT_PUBLIC_API_URL` is build-time; changing the API domain requires a **web
  rebuild**, not just a restart.
- The worker is an interval scheduler (no Celery/Temporal yet); it is idempotent
  per tick and lease-arbitrated, so running more than one replica is safe (the
  lease prevents duplicate runs) but there is no central schedule coordinator.
- Postgres RLS is enforced in `004_rls_policies.sql`; verify with
  `scripts/check_rls_policies.py` against the Railway database.
