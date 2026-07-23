# Production Readiness — MemoryOps AI (v1.0)

What "production-ready governed memory runtime" means for v1.0: the governed memory
lifecycle, its seven non-negotiable invariants, and the cross-cutting planes are
implemented, enforced in code + tests, and operable. This page maps each guarantee
to where it lives, and states plainly what is production-capable vs demo-only.

For the inverse (what is *not* claimed), see [limitations.md](limitations.md).

## The seven invariants (enforced in code + tests)

| # | Invariant | Where enforced |
|---|-----------|----------------|
| 1 | Tenant isolation | Repository scoped reads/writes; Postgres RLS (`FORCE`); `scripts/check_rls_policies.py`; `tests/test_rls.py` |
| 2 | Deletion guarantee | `status='deleted'` excluded from all retrieval; deletion verification worker; `tests/` |
| 3 | Provenance | `source` is NOT NULL on every memory; preserved through compaction (`source.kind`) |
| 4 | Graceful degradation | Retrieval failure degrades to keyword-only; workers never raise into chat |
| 5 | Policy-before-storage | Policy broker runs before any write; LLM output is advisory |
| 6 | Temporary chat | `temporary_chat=true` reads/writes nothing |
| 7 | Auditability | Every lifecycle mutation and its audit event commit atomically in one `repo.transaction()` (append-only, fork-proof; ADR-027) |

## Cross-cutting planes

- **Security** — tenant isolation, enforced RLS, secret detection/redaction before
  storage, deletion guarantee. See [security.md](security.md).
- **Governance** — capture/evaluate/approve/forget lifecycle, retention policy
  packs, legal hold (fail-closed), consent-aware eligibility, deletion compaction +
  vector purge verification, full audit trail. See [governance.md](governance.md),
  [retention-policies.md](retention-policies.md).
- **Reliability** — worker runtime with leases (no duplicate runs), retry/backoff,
  dead-letter, persisted run history, `GET /healthz/workers`. See
  [worker-runtime.md](worker-runtime.md).
- **Observability** — structured logs, audit events, worker run history, loop
  timelines (`/api/loops`), Prometheus metrics (`GET /metrics`), and distributed
  tracing with an optional OpenTelemetry bridge (`GET /api/traces`). Collector/
  dashboard deployment and Langfuse LLM-trace wiring are left to the operator.
- **Evaluation** — golden + adversarial eval suite (`evals/run_evals.py`) plus the
  invariant test suite and the deterministic PR Invariant Evidence Gate.

## Production-capable vs demo-only

| Capability | Production-capable | Demo-only |
|------------|--------------------|-----------|
| Storage | Postgres + pgvector, enforced RLS | In-memory backend (dev/tests, playground) |
| LLM / embeddings | OpenAI / Anthropic / Gemini adapters | Deterministic offline stubs (default) |
| UI | Next.js app (`apps/web`) | Results dashboard (v0.9), Playground (v0.12) |
| Workers | Lease/scheduler runtime (`services/worker`) | One-shot `runner.py` invocations |
| Client | Typed Python SDK (`memoryops-sdk`) | Example scripts |

## Production profile (fail-closed startup)

The defaults are demo-friendly so the app runs with zero infra (in-memory store,
`auth_mode=none`, open CORS). Set **`MEMORYOPS_PROFILE=production`** on real
deployments: the API then **refuses to start** while any of those insecure defaults
remain, instead of silently serving production traffic with them. It rejects:

| Rejected setting | Fix |
|------------------|-----|
| `MEMORYOPS_STORAGE=memory` (no durability, no RLS) | `MEMORYOPS_STORAGE=postgres` |
| `MEMORYOPS_AUTH_MODE=none` (unauthenticated) | `MEMORYOPS_AUTH_MODE=jwt` \| `trusted_header` |
| open CORS (`*`) | `MEMORYOPS_CORS_ALLOW_ORIGINS=https://app.example.com,…` |
| bundled demo DB credentials / `localhost` DSN | real `MEMORYOPS_DATABASE_URL` / `DATABASE_URL` |
| `MEMORYOPS_PUBLIC_EVALS=true` (denial-of-wallet) | `MEMORYOPS_PUBLIC_EVALS=false` |

The check is enforced only under the production profile (`dev` is unchanged) and is
implemented in `Settings.production_readiness_errors()` — see `tests/test_production_profile.py`.

**Readiness** (`GET /readyz`) reports **dependency-specific** states rather than one
combined string: `storage`, `schema` (migration revision), `vector_backend`,
`worker_runtime`, `llm_provider`, `embedding_provider` — each `ok` / `skipped` /
`error`. `ready` is false iff any dependency is in `error` (a `skipped` backend that
isn't selected never blocks readiness). Every probe is no-throw (invariant #4).

## Deploying

Railway-only: one project, five core services (web/api/worker + Postgres + Redis).
Run migrations from `infra/db/migrations`; set `MEMORYOPS_STORAGE=postgres` and
`MEMORYOPS_PROFILE=production`.
Configure authentication: either enable a built-in auth adapter
(`MEMORYOPS_AUTH_MODE=jwt` or `trusted_header`, which verify identity and enforce
tenant/user scope — see [auth-adapters.md](auth-adapters.md)), or, with the default
`MEMORYOPS_AUTH_MODE=none`, front the API with your own auth (it then trusts the
caller-supplied `tenant_id`/`user_id` scope). Either way, identity issuance stays
with your IdP. See [deployment/railway.md](deployment/railway.md).

## Release gate (must be green to ship)

```bash
cd services/api && pytest -q && ruff check app
cd evals && python run_evals.py
python scripts/pr_invariant_gate.py --base main --head HEAD
cd apps/web && npm run build
```

See [release-loop.md](release-loop.md) and [RELEASING.md](../RELEASING.md).

## Stability

The public HTTP API and SDK surface are **stable** as of v1.0 under a `1.x`
additive-compatibility promise — see [api-stability.md](api-stability.md).
