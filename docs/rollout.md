# Rollout — MemoryOps AI

Phased delivery. Status reflects this repository.

| Phase | Scope | Status |
|-------|-------|--------|
| 0 | Design spine: README, architecture/security/governance docs, ADRs, DB schema, API contracts | ✅ Done |
| 1 | Core write path: gateway → extractor → policy broker → write service → store → audit | ✅ Done |
| 2 | Read path: retriever → ranker → context composer → memory-used response | 🟡 Scaffolded |
| 3 | Governance UI: approve/reject, edit, archive, delete, audit viewer | 🟡 Scaffolded |
| 4 | Production depth: pgvector embeddings, RLS enforcement, evals, observability | 🟡 Partial |
| 5 | Background intelligence: decay, reflection, conflict resolution, compression | 🟡 Stubbed |
| 6 | Submission polish: landing/architecture pages, demo, screenshots | 🟡 In progress |

## Phase 0 — Design spine ✅
Deliverables: `README.md`, `docs/architecture.md`, `docs/security.md`, `docs/governance.md`,
`docs/rollout.md`, `docs/demo-script.md`, `infra/adr/ADR-001..005`, DB migrations, API contracts.
**Done when:** a reviewer can understand the system without running it.

## Phase 1 — Core write path ✅
Explicit capture, typed classification, importance/confidence/sensitivity scoring,
block/drop/save/pending decisions, provenance, audit events.
**Done when:** "Remember that…" stores the right memory and a fake API key is blocked.

## Phase 2 — Read path 🟡
Tenant/user filtering, active-only retrieval, keyword + vector-ready retrieval, ranking, compact
context block, memory-used badges. Interfaces exist in `app/services/retriever.py`,
`ranker.py`, `context_composer.py`; chat returns `used_memories`.
**Done when:** future chats use relevant memory and deleted/pending memory is never retrieved.

## Phase 3 — Governance dashboard 🟡
`PATCH`/`DELETE` endpoints exist; UI actions to be fully wired.

## Phase 4 — Enterprise security & evals 🟡
RLS-ready schema (enable → enforce), pgvector index, golden + adversarial eval cases, `run_evals.py`.

## Phase 5 — Background intelligence 🟡
`services/worker` job stubs for decay, reflection/compression, conflict resolution, reinforcement.

## Production roadmap (beyond hackathon)

- Swap heuristic LLM/embeddings for provider adapters (OpenAI/Anthropic/Gemini).
- Enforce Postgres RLS; field-level encryption for high-sensitivity rows.
- Observability: OpenTelemetry traces → Tempo/Jaeger; metrics → Prometheus/Grafana; LLM traces →
  Langfuse.
- Workers on Celery/Temporal with retries + dead-letter queues.
- Deploy: API on Railway/Render, web on Vercel, managed Postgres (pgvector) + Redis.
- Cost controls: cache embeddings, batch extraction, track cost per write/retrieval.
