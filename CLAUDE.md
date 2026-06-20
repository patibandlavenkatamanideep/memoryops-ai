# CLAUDE.md — MemoryOps AI working notes

> The authoritative product/architecture brief is [CLAUDE_ENTERPRISE.md](CLAUDE_ENTERPRISE.md).
> This file is the short operational guide for working in the repo.

## What this is

MemoryOps AI is a governed memory lifecycle system for AI assistants — not a chatbot with memory.
The lifecycle is: **Capture → Evaluate → Store → Retrieve → Rank → Compose → Update → Forget → Audit**,
wrapped by Security, Governance, Observability, Reliability, Evaluation planes.

## Non-negotiable invariants (enforced in code + tests)

1. Tenant isolation — every memory query filters by `tenant_id` + `user_id`.
2. Deletion guarantee — `status='deleted'` rows are never retrieved.
3. Provenance — every memory has a non-null `source`.
4. Graceful degradation — retrieval failures never block responses.
5. Policy-before-storage — the policy broker runs before any write.
6. Temporary chat — `temporary_chat=true` writes/reads nothing.
7. Auditability — every lifecycle action appends an audit event.

## Layout

- `services/api` — FastAPI. Write path lives in `app/services/` (extractor, policy_broker,
  write_service) and is orchestrated by `app/services/gateway.py`.
- `services/api/app/db` — repository abstraction. `MEMORYOPS_STORAGE=memory|postgres`.
- `infra/db/migrations` — SQL schema (Postgres + pgvector).
- `apps/web` — Next.js frontend.
- `evals` — golden + adversarial cases, `run_evals.py`.

## Running

```bash
# API (no infra):
cd services/api && pip install -r requirements.txt && \
  MEMORYOPS_STORAGE=memory uvicorn app.main:app --reload

# Tests:
cd services/api && pip install -r requirements-dev.txt && pytest -q

# Full stack:
docker compose up --build
```

## Conventions

- New lifecycle actions MUST emit an audit event via `AuditService`.
- New retrieval paths MUST go through the repository's tenant-scoped methods.
- Keep the heuristic fallback working with no API keys; LLM adapters are optional enhancements.
- Phase status is tracked in `docs/rollout.md`.
