# Phase 13 — Infrastructure & Deployment

**Question:** How does the system get built, shipped, and run in production?

## MemoryOps mapping
A single **Railway** project hosts the whole stack — no Vercel, no split host.
Five services in one project: `memoryops-web` (Next.js), `memoryops-api`
(FastAPI), `memoryops-worker` (background loops), Railway Postgres (+pgvector),
Railway Redis. Build is Dockerfile-per-service; deploy/build settings are
config-as-code under `railway/`.

## Gate (must be true to pass)
- Deployment target is **Railway only**; Vercel is not a recommended path.
- Each service has a checked-in config (`railway/{api,web,worker}.railway.json`).
- API binds `$PORT` and exposes `/healthz` (liveness) + `/readyz` (readiness).
- Env contract is documented per service, with safe no-key defaults.
- A repeatable post-deploy smoke test exists and is runnable from any shell.
- Migrations are forward-only and additive (older API runs on newer schema).

## Evidence
- [docs/deployment/railway.md](../deployment/railway.md) — topology, order, rollback.
- [docs/deployment/railway-env.md](../deployment/railway-env.md) — env matrix.
- [docs/deployment/railway-smoke-test.md](../deployment/railway-smoke-test.md).
- [railway/api.railway.json](../../railway/api.railway.json),
  [web.railway.json](../../railway/web.railway.json),
  [worker.railway.json](../../railway/worker.railway.json).
- [scripts/railway_smoke_test.py](../../scripts/railway_smoke_test.py).
- [services/api/app/routes/health.py](../../services/api/app/routes/health.py)
  (`/healthz`, `/readyz`).

## Gaps to close (→ later)
- CI auto-deploy hook on tag (currently manual redeploy on Railway).
- Multi-replica API + worker on Celery/Temporal with retries/DLQ.
- Build-time `NEXT_PUBLIC_API_URL` requires a web rebuild on API domain change.

## Status: ✅ Implemented (Railway-only; CI auto-deploy is roadmap)
