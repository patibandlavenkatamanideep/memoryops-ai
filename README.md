# MemoryOps AI

MemoryOps AI is an enterprise-shaped memory governance layer for AI assistants. It implements a
ChatGPT-style memory lifecycle with capture, policy evaluation, typed storage, hybrid retrieval,
controlled forgetting, auditability, and tenant isolation.

Most demos treat memory as a vector database. MemoryOps AI treats memory as **governed state**.

> **Tagline:** Enterprise memory governance for AI assistants.
> **Core claim:** Memory is not a database. Memory is a governed decision system that decides what
> information is valuable enough to carry into the future.

---

## Why this exists

Most AI "memory" demos do this:

```text
chat message → vector database → retrieve later
```

MemoryOps AI does this:

```text
WRITE PATH
Message → Extractor → Evaluator / Policy Broker → Write Service → Typed Memory Stores → Audit Log

READ PATH
Message → Retriever → Ranker → Context Composer → Response LLM

BACKGROUND
Decay Job → Reflection Agent → Conflict Resolver → Compression Worker

CROSS-CUTTING PLANES
Security · Governance · Observability · Evaluation · Reliability
```

The five verbs the system must demonstrate:

```text
Capture → Store → Retrieve → Update → Forget   (Governance wraps all five)
```

---

## Enterprise invariants

These are non-negotiable and are enforced in code and tests.

1. **Tenant isolation** — User A's memory is never returned to User B or another tenant.
2. **Deletion guarantee** — Deleted memories are never retrieved again.
3. **Provenance** — Every stored memory traces back to its source message/document/manual input.
4. **Graceful degradation** — Retrieval failure never blocks response generation.
5. **Policy-before-storage** — Unsafe / secret-like content is filtered before it reaches the store.
6. **Temporary chat** — Temporary sessions never write or retrieve memory.
7. **Auditability** — Every memory lifecycle event produces an append-only audit event.
8. **Explainability** — The system can show which memories affected a response.
9. **Typed memory** — Episodic, semantic, procedural, project, knowledge, system memories differ.
10. **Evaluation** — Memory quality is testable through a golden set, not just manual inspection.

See [docs/architecture.md](docs/architecture.md) for the full design and where each invariant is
enforced.

---

## Repository layout

```text
memoryops-ai/
  apps/web/            Next.js frontend (chat, memory dashboard, admin, architecture)
  services/api/        FastAPI backend (gateway, extractor, policy broker, write/read path, audit)
  services/worker/     Background jobs (decay, reflection, conflict resolution, compression)
  packages/shared/     Shared types
  infra/db/            Postgres + pgvector migrations and seed
  infra/adr/           Architecture Decision Records
  infra/observability/ OpenTelemetry / metrics notes
  evals/               Golden + adversarial cases and the eval runner
  docs/                architecture, security, governance, rollout, demo-script
  docker-compose.yml
```

---

## Quickstart

### Option A — API only, no infra (fastest)

The API ships with an in-memory repository so you can run the write path and tests without Postgres.

```bash
cd services/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export MEMORYOPS_STORAGE=memory          # default; uses in-memory store
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000/docs
```

Run the invariant test suite:

```bash
cd services/api
pip install -r requirements-dev.txt
pytest -q
```

Run the eval harness against a running API (or in-process):

```bash
cd evals
python run_evals.py
```

### Option B — Full stack with Docker Compose

```bash
cp .env.example .env
docker compose up --build
# web  → http://localhost:3000
# api  → http://localhost:8000/docs
# db   → localhost:5432 (postgres/pgvector)
# redis→ localhost:6379
```

Compose runs migrations from `infra/db/migrations` on first boot and sets
`MEMORYOPS_STORAGE=postgres` for the API.

### Frontend

```bash
cd apps/web
npm install
npm run dev          # http://localhost:3000
```

The frontend reads `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`).

---

## What works today (Phase 0 + Phase 1)

- Full design spine: README, architecture/security/governance/rollout docs, 5 ADRs, DB schema.
- FastAPI write path: **Gateway → Extractor → Policy Broker → Write Service → Memory Store → Audit**.
- Heuristic extractor + policy broker (works with **no API keys**); pluggable LLM adapter interface.
- Typed memory classification, importance/confidence/sensitivity scoring, provenance capture.
- Policy decisions: `SAVE`, `PENDING_APPROVAL`, `BLOCK`, `DROP_LOW_UTILITY`, `UPDATE_EXISTING`, `MERGE_WITH_EXISTING`.
- Secret / PII detection blocks API keys and credentials before storage.
- Append-only audit log for every lifecycle event.
- Temporary chat short-circuits both read and write.
- Memory dashboard + admin/audit + architecture pages (frontend skeleton).
- Invariant test suite + eval harness scaffolding.

## What remains (Phase 2+)

- Phase 2: hybrid retriever + ranker + context composer wired into chat responses.
- Phase 3: governance UI actions (approve/edit/archive/delete) fully wired.
- Phase 4: pgvector embeddings, RLS enforcement, richer eval coverage.
- Phase 5: decay / reflection / conflict-resolution workers.

See [docs/rollout.md](docs/rollout.md) and the build phases in [CLAUDE.md](CLAUDE.md).

---

## Documentation

- [docs/architecture.md](docs/architecture.md) — write path, read path, planes, invariants.
- [docs/security.md](docs/security.md) — tenant isolation, secret detection, deletion guarantee.
- [docs/governance.md](docs/governance.md) — lifecycle, approvals, audit, retention.
- [docs/rollout.md](docs/rollout.md) — phased delivery and production roadmap.
- [docs/demo-script.md](docs/demo-script.md) — the 6-step demo.
- [infra/adr/](infra/adr/) — storage, retrieval, policy broker, observability, deletion ADRs.
