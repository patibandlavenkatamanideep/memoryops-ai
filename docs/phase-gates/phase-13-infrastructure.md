# Phase 13 — Infrastructure & Deployment

**Question:** How does the system get built, shipped, and run in production?

## MemoryOps mapping
A single **Railway** project hosts the whole stack — no Vercel, no split host.
**Four** services in one project: `memoryops-web` (Next.js), `memoryops-api`
(FastAPI), `memoryops-worker` (background loops), and Railway Postgres (+pgvector).
Redis was removed: it was declared, health-gated and paid for while no runtime code
ever read `REDIS_URL`. Build is Dockerfile-per-service; deploy/build settings are
config-as-code under `railway/`.

## Gate (must be true to pass)
- Deployment target is **Railway only**; Vercel is not a recommended path.
- Each service has a checked-in **canonical** config
  (`railway/{api,web,worker,playground}.railway.json`), and **exactly one** config
  source per service.
- The **Dockerfile `CMD` owns the start command**. Configs do not set
  `startCommand`, and no config contains a literal `$PORT` — it does not expand in
  exec form.
- API exposes `/healthz` (liveness) + `/readyz` (readiness). It binds a fixed port
  `8000` with `EXPOSE 8000`; Railway routes to the detected port.
- Web health check is `/architecture`. **Not `/`** — in `authenticated` mode the root
  answers 307 to `/signin`, so a check there can never pass.
- Worker has **no** HTTP health check (it binds no port). Its health is read from the
  API's `GET /healthz/workers`, which must report `{"healthy": true}` — requiring
  `OPERATIONAL_DATABASE_URL` and the restricted `memoryops_monitor` role.
- Env contract is documented per service, with safe no-key defaults, and covers the
  web authentication variables (`AUTH_SECRET`, `AUTH_TRUST_HOST`,
  `MEMORYOPS_WEB_MODE`, `MEMORYOPS_WEB_OPERATORS`).
- A repeatable post-deploy **release gate** exists and is runnable from any shell:
  `scripts/release_smoke_v24.py` (`FAILED 0 / SKIPPED 0 / RESULT: PASS`).
- Migrations are forward-only and additive (older API runs on newer schema).

## Evidence
- [docs/deployment/railway.md](../deployment/railway.md) — topology, per-service
  settings, deploy order, the `$PORT` rule, rollback.
- [docs/deployment/railway-env.md](../deployment/railway-env.md) — env matrix incl.
  web auth variables and the `memoryops_monitor` operational role.
- [docs/deployment/railway-smoke-test.md](../deployment/railway-smoke-test.md) —
  which smoke test is the release gate and which is liveness-only.
- [docs/releases/RELEASE-PROCESS.md](../releases/RELEASE-PROCESS.md) — release
  evidence model, SHA identity, tagging rules.
- [railway/api.railway.json](../../railway/api.railway.json),
  [web.railway.json](../../railway/web.railway.json),
  [worker.railway.json](../../railway/worker.railway.json),
  [playground.railway.json](../../railway/playground.railway.json).
- [scripts/release_smoke_v24.py](../../scripts/release_smoke_v24.py) — release gate.
- [scripts/railway_smoke_test.py](../../scripts/railway_smoke_test.py) — quick
  liveness smoke; **not** proof of authorization correctness.
- [scripts/repo_trust_guards.py](../../scripts/repo_trust_guards.py) —
  `railway-deployment-config` guard enforces the config rules above.
- [services/api/app/routes/health.py](../../services/api/app/routes/health.py)
  (`/healthz`, `/readyz`, `/healthz/workers`).

## Config-source migration status (v2.4.1)
`railway/*.railway.json` is canonical. `services/api/railway.toml` **still exists**
as a temporary production-compatibility file, because the Railway API service
currently reads it. The trust guard permits this one duplicate by name
(`TRANSITIONAL_DUPLICATE_CONFIGS`); any other service gaining a second source is a
finding today.

**Phase B — not yet done:** point the API service's Config File at
`railway/api.railway.json` → redeploy → run the release gate → delete the TOML →
remove the guard exception, which tightens enforcement to exactly one source per
service. Checkpoint lives in
[docs/deployment/railway.md](../deployment/railway.md#config-as-code).

## Gaps to close (→ later)
- Complete the Phase B config-source switchover (above).
- CI auto-deploy hook on tag (currently manual redeploy on Railway).
- API binds a fixed `8000` rather than the injected `$PORT`; making it dynamic needs
  a Dockerfile `sh -c` change plus a deploy window.
- `MEMORYOPS_AUTH_JWT_KEY` is not validated at startup — with `auth_mode=jwt` and no
  key the API boots and then rejects every credential.
- Multi-replica API + worker on Celery/Temporal with retries/DLQ.
- Build-time `NEXT_PUBLIC_API_URL` requires a web rebuild on API domain change.

## Status: ✅ Implemented (Railway-only; config-source consolidation in Phase B, CI auto-deploy is roadmap)
