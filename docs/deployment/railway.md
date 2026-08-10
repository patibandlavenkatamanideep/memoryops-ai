# Deploying MemoryOps AI on Railway

MemoryOps AI deploys to **Railway only**. There is no Vercel target and no
split-host topology — the frontend, backend, worker, and database all live in
**one Railway project** as separate services. This keeps env wiring, private
networking, and the deploy story in a single place.

> Vercel is **not** a supported or recommended deployment path. If you see Vercel
> referenced anywhere, treat it as historical.

## Target architecture

**Railway project:** `memoryops-ai`

| # | Service | Role | Source | Health |
|---|---------|------|--------|--------|
| 1 | `memoryops-web` | Next.js frontend | `apps/web/Dockerfile` | `GET /architecture` |
| 2 | `memoryops-api` | FastAPI backend | `services/api/Dockerfile` | `GET /healthz`, `GET /readyz` |
| 3 | `memoryops-worker` | Background jobs (decay/reflection/learning loop) | `services/worker/Dockerfile` | process liveness (no HTTP) |
| 4 | Railway **Postgres** | Primary store + pgvector | Railway plugin | managed |

`memoryops-playground` is an **optional** demo service, not part of the production
topology. Its config is checked in and ready, but the four rows above are what a
production deployment requires.

All four run inside the same project so they share Railway's private network and
reference each other through Railway-provided variables (e.g. `DATABASE_URL`).
See [railway-env.md](railway-env.md) for the full variable matrix.

> **Redis was removed from the topology.** It was previously listed as a required
> fifth service, started by Compose, and health-gated by both the API and the worker
> — but no runtime code ever read `REDIS_URL`, and no Redis client was imported
> anywhere in the repo. A declared-but-unused dependency is pure cost: another
> managed service to pay for, another health check that can fail a deploy, and a
> misleading architecture diagram. Reinstate it when something actually uses it
> (distributed rate limiting, job queueing, caching, pub/sub, cross-replica
> coordination).

## Config-as-code

`railway/*.railway.json` is the **canonical** configuration source:

| Service | Config File |
|---------|-------------|
| `memoryops-api` | `/railway/api.railway.json` |
| `memoryops-web` | `/railway/web.railway.json` |
| `memoryops-worker` | `/railway/worker.railway.json` |
| `memoryops-playground` *(optional)* | `/railway/playground.railway.json` |

Point each Railway service at its config file via **Service → Settings → Config
File**. Builder is `DOCKERFILE` for all of them.

The **leading `/` matters**: a Railway Config File path is absolute from the
repository root and does *not* inherit the service's Root Directory. `dockerfilePath`
*inside* the config follows the opposite rule — it is relative to Root Directory.
Those two are easy to get backwards, and "Dockerfile not found" is what it looks like
when you do.

Explicit per-service config paths are used rather than a `railway.toml` at each
service root because Railway auto-detects `railway.toml` relative to a service's
**Root Directory**, and both the worker and the playground are rooted at the
repository root — they would collide on a single top-level file.

### The Dockerfile owns the start command

None of `api`, `web`, or `worker` sets `deploy.startCommand`. Their Dockerfile `CMD`
is authoritative. Declaring the launch in two places is how the two drift, and it is
what broke the v2.4 deployment (below). `scripts/repo_trust_guards.py` enforces this.

### Exactly one config source per service

Every production service reads its configuration from the canonical file above, and
from nothing else. `scripts/repo_trust_guards.py` enforces this: a second config
source for any service is a finding.

The API briefly carried a transitional `services/api/railway.toml` while Railway's
Config File setting still pointed at it. That migration completed in v2.4.1 — the
three services were switched to their canonical JSON one at a time, production was
re-verified after each, and the TOML was removed. Nothing in the repository describes
a Railway service any more except `railway/*.railway.json`.

## Per-service settings

Set these in **Service → Settings** for each service. `dockerfilePath` in the
config files is resolved relative to the service **Root Directory**.

> **Root Directory** and **Config File** are Railway *service-level* settings. They
> cannot be expressed in config-as-code — a config file cannot say where it lives.
> They must be set deliberately in the dashboard, and they are the two settings most
> likely to be wrong on a rebuilt project. Record them here whenever they change.

### 1. `memoryops-api`
- **Root Directory:** `services/api`
- **Config File:** `/railway/api.railway.json`
- **Dockerfile path:** `Dockerfile` (relative to root)
- **Start command:** owned by the **Dockerfile `CMD`** —
  `uvicorn app.main:app --host 0.0.0.0 --port 8000`. Not set in config.
- **Health check path:** `/healthz`
- **Port 8000 is deliberate.** The image declares `EXPOSE 8000` and binds it, and
  Railway routes to the detected listening port. Do **not** "fix" this by putting
  `$PORT` in a config `startCommand` — see the rule below.

### 2. `memoryops-web`
- **Root Directory:** `apps/web`
- **Config File:** `/railway/web.railway.json`
- **Dockerfile path:** `Dockerfile` (relative to root)
- **Start command:** owned by the **Dockerfile `CMD`** — `npm run start`. Not set in config.
- **Health check path:** `/architecture`
- **Not `/`.** In `authenticated` mode `/` answers **307 → `/signin`**, so a health
  check pointed at it can never succeed. `/architecture` renders without a session.
- `NEXT_PUBLIC_API_URL` must be set at **build time** to the public `memoryops-api`
  URL (Next.js inlines `NEXT_PUBLIC_*` at build).

### 3. `memoryops-worker`
- **Root Directory:** repo root (`/`) — the worker image copies `services/api`
  into the build, so its build context must be the repository root.
- **Config File:** `/railway/worker.railway.json`
- **Dockerfile path:** `services/worker/Dockerfile` (relative to repo root)
- **Start command:** owned by the **Dockerfile `CMD`** — `memoryops-worker` (the
  packaged console script). Not set in config.
- **No HTTP health check, deliberately.** The worker is an interval scheduler, not a
  web server — it binds no port, so there is nothing for Railway to probe. Adding a
  health check would require inventing an HTTP surface purely to satisfy the
  platform, and a fake endpoint that returns 200 while the scheduler is wedged is
  worse than no endpoint. Railway restarts on process exit
  (`restartPolicyType: ON_FAILURE`); liveness is process liveness.
- Set `MEMORYOPS_WORKER_SCOPES="tenant:user,…"` and optionally
  `MEMORYOPS_WORKER_INTERVAL_SECONDS`. **Without scopes the worker starts, reports
  healthy, and processes nothing.**
- **Worker health is observable via the API** at `GET /healthz/workers` — which
  requires `OPERATIONAL_DATABASE_URL` on the *API* service, not on the worker. See
  [railway-env.md](railway-env.md#operational-monitoring-role) and
  [worker-runtime.md](../worker-runtime.md).

## Deployment order

Provision and deploy in this order so dependencies are ready:

1. **Postgres** plugin — then apply every migration in `infra/db/migrations` in
   lexical order:

   ```bash
   for f in infra/db/migrations/*.sql; do
     echo "-- applying $f"
     psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
   done
   ```

   Do **not** hand-maintain a migration list here. This guide previously said to
   apply `001…007` and called `007_retention_legal_hold_consent.sql` "the latest"
   while the repository had migrations through `011` — following it produced a
   database missing the scope-id, operational-evidence, transactional audit-chain,
   and chain-head schema. The glob above cannot go stale.

2. **`memoryops-api`** — set the production variables below. Wait for `/readyz` to
   report `ready: true` (and check `degraded: false`).
3. **`memoryops-worker`** — same `DATABASE_URL` / `MEMORYOPS_STORAGE`, plus
   `MEMORYOPS_WORKER_SCOPES`.
4. **`memoryops-web`** — set `NEXT_PUBLIC_API_URL` to the public API domain, then
   deploy (build-time inline).

### Minimum production variables

`MEMORYOPS_PROFILE=production` is fail-closed: the API refuses to start if any of
these is unsafe (`Settings.production_readiness_errors`). The previous "minimum
set" in this guide omitted several values the profile itself requires, so following
it produced a service that would not boot.

```bash
MEMORYOPS_PROFILE=production
MEMORYOPS_STORAGE=postgres
MEMORYOPS_AUTH_MODE=jwt              # or trusted_header; 'none' is rejected
MEMORYOPS_CORS_ALLOW_ORIGINS=https://<your-web-domain>   # '*' is rejected
MEMORYOPS_PUBLIC_EVALS=false
DATABASE_URL=<reference the Postgres plugin>
OPERATIONAL_DATABASE_URL=<restricted monitoring role>    # enables /healthz/workers
MEMORYOPS_WORKER_SCOPES=<tenant:user,…>                  # worker service
NEXT_PUBLIC_API_URL=https://<your-api-domain>            # web service, build-time
```

If you select a networked provider, its SDK ships in the production image but the
key must be set — `MEMORYOPS_LLM_PROVIDER=openai` without `OPENAI_API_KEY` is a
startup error in this profile rather than a silent downgrade to the stub. See
[dependency-management.md](../dependency-management.md).

After all four are up, run the smoke test
([railway-smoke-test.md](railway-smoke-test.md)).

## Optional: Playground demo service (v0.12)

The public [Playground](../playground.md) (`apps/playground`) can be deployed as an
**optional** demo service — it is **not** one of the five core services. It needs
**no database and no secrets** (in-memory store + offline stubs), so it is safe to
host. Its Dockerfile copies `services/api`, so the Docker build context must be the
**repository root**:

- **Root Directory:** `/` (repo root) — **not** `apps/playground`.
- **Config File (config-as-code):** `/railway/playground.railway.json` — this is what
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

- `memoryops-api`: Railway hits `healthcheckPath=/healthz` on the detected listening
  port. `/readyz` additionally touches the repository so a misconfigured DB surfaces
  as not-ready (useful for manual verification).
- `memoryops-web`: `healthcheckPath=/architecture`. **Not `/`** — in `authenticated`
  mode the root answers 307 to `/signin`, so a check pointed there never passes. It
  works in demo mode, which is exactly why the mistake survives review.
- `memoryops-worker`: no HTTP probe; Railway restarts on process exit
  (`restartPolicyType: ON_FAILURE`). Health is read from the API's
  `GET /healthz/workers`, which needs `OPERATIONAL_DATABASE_URL` and must report
  `{"healthy": true}` — the release smoke gate requires exactly that.

## Rollback

- Railway keeps prior deployments per service. To roll back, open the service →
  **Deployments** → pick the last-good deployment → **Redeploy**.
- Roll back **web** and **api** independently; they are decoupled by
  `NEXT_PUBLIC_API_URL`.
- Database migrations are **forward-only**. A rollback of the API does not revert
  schema; keep migrations additive (as `005_loop_engineering.sql` is) so an older
  API image still runs against a newer schema.

## Known limitations

- The API binds a fixed port `8000` (Dockerfile `CMD` + `EXPOSE 8000`) and relies on
  Railway detecting it, rather than binding the injected `$PORT`. This is a
  deliberate, working arrangement, not an oversight. Making the API bind `$PORT`
  would require a Dockerfile change (`sh -c` so the variable expands) plus a deploy
  window, and is out of scope for v2.4.1. The in-image `HEALTHCHECK` is cosmetic in
  production; Railway uses `healthcheckPath`.

### The `$PORT` rule

**Never place an unexpanded literal `$PORT` inside a Railway config-as-code
`startCommand` for a Dockerfile service.**

A config `startCommand` on a Dockerfile service runs in **exec form, without shell
expansion** — the process receives the four characters `$PORT`, not a port number.
This broke the v2.4 API deployment. The playground had already hit and documented the
same failure; that precedent did not prevent the second occurrence, so it is now a
guard (`railway-deployment-config` in `scripts/repo_trust_guards.py`) rather than a
paragraph.

If a service genuinely needs dynamic port binding, expand it in the **Dockerfile
`CMD` through a shell**, the way the playground does:

```dockerfile
CMD ["sh", "-c", "streamlit run streamlit_app.py --server.port ${PORT:-8501} ..."]
```
- `NEXT_PUBLIC_API_URL` is build-time; changing the API domain requires a **web
  rebuild**, not just a restart.
- The worker is an interval scheduler (no Celery/Temporal yet); it is idempotent
  per tick and lease-arbitrated, so running more than one replica is safe (the
  lease prevents duplicate runs) but there is no central schedule coordinator.
- Postgres RLS is enforced in `004_rls_policies.sql`; verify with
  `scripts/check_rls_policies.py` against the Railway database.
