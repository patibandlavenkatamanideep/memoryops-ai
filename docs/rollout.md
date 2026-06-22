# Rollout — MemoryOps AI

Phased delivery. Status reflects this repository.

| Phase | Scope | Status |
|-------|-------|--------|
| 0 | Design spine: README, architecture/security/governance docs, ADRs, DB schema, API contracts | ✅ Done |
| 1 | Core write path: gateway → extractor → policy broker → write service → store → audit | ✅ Done |
| 2 | Read path: retriever → ranker → context composer → memory-used response | 🟡 Scaffolded |
| 3 | Governance UI: approve/reject, edit, archive, delete, audit viewer | ✅ Done (v0.5) |
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

## Phase 3 — Governance dashboard ✅ (v0.5)
Browser memory control plane: `/memories`, `/memories/[id]`, `/governance`,
`/audit`. View/filter, detail with provenance + per-memory audit timeline, inline
edit, approve/reject queue, archive/restore, soft-delete, and recorded policy
decisions. Additive read routes (`GET /api/memories/{id}`, `/{id}/provenance`,
`/{id}/audit`) + `memory_id` audit filter; every action is audited and the policy
broker stays authoritative. See [governance-ui.md](governance-ui.md),
[memory-control-plane.md](memory-control-plane.md),
[ADR-009](../infra/adr/ADR-009-memory-control-plane.md).

## Phase 4 — Enterprise security & evals 🟡
RLS-ready schema (enable → enforce), pgvector index, golden + adversarial eval cases, `run_evals.py`.

## Phase 5 — Background intelligence ✅ workers landed (v0.6)
Background memory lifecycle workers (`services/api/app/workers/`) implement the
*Update → Forget* arc off the chat path: **decay**, **archive**, **deletion
verification**, **conflict scan**, and proposal-only **reflection** (off by
default), driven by a tenant-scoped `runner`. Every job is tenant scoped,
idempotent, retry-safe, audited, and unable to resurrect deleted memory; the
policy broker stays authoritative. Conflict resolution and reflection remain
*proposal-only* (review candidates, no auto-overwrite/auto-write). See
[background-lifecycle-workers.md](background-lifecycle-workers.md),
[memory-decay-policy.md](memory-decay-policy.md),
[deletion-verification.md](deletion-verification.md),
[ADR-010](../infra/adr/ADR-010-background-memory-lifecycle-workers.md).

## Phase 5 (cont.) — Deletion compaction + vector purge ✅ (v0.7)
A sixth lifecycle job, **deletion compaction**, clears soft-deleted memory's
content + vector material after a retention window, preserves the governance
tombstone + audit trail, and **verifies** the purge fail-closed. Additive
repository methods (`list_deleted_for_compaction`, `compact_deleted_memory`) keep
it isolated. Honest scope: auditable content/vector compaction + retrieval-exclusion
verification — **not** crypto-shred or guaranteed physical disk/index reclamation.
See [deletion-compaction.md](deletion-compaction.md),
[vector-purge-verification.md](vector-purge-verification.md),
[phase-gates/phase-13-deletion-compaction-vector-purge.md](phase-gates/phase-13-deletion-compaction-vector-purge.md),
[ADR-011](../infra/adr/ADR-011-physical-deletion-compaction-vector-purge.md).

## Public roadmap

| Version | Scope | Status |
|---------|-------|--------|
| v0.7 | Physical deletion compaction + vector purge verification | ✅ Done |
| v0.8 | Railway worker runtime + scheduled lifecycle orchestration | ⏳ Next |
| v0.9 | Retention policies + legal hold + consent-aware memory | ⏳ Planned |
| v0.10 | Assistant SDK + example apps | ⏳ Planned |
| v1.0 | Production-ready governed memory runtime | ⏳ Planned |

## Production roadmap (beyond hackathon)

- Swap heuristic LLM/embeddings for provider adapters (OpenAI/Anthropic/Gemini).
- Enforce Postgres RLS; field-level encryption for high-sensitivity rows.
- Observability: OpenTelemetry traces → Tempo/Jaeger; metrics → Prometheus/Grafana; LLM traces →
  Langfuse.
- Workers on Celery/Temporal with retries + dead-letter queues.
- Deploy: **Railway only** — one project, five services (web, api, worker,
  managed Postgres+pgvector, Redis). No Vercel. See
  [docs/deployment/railway.md](deployment/railway.md). (Aligned in v0.3.2.)
- Cost controls: cache embeddings, batch extraction, track cost per write/retrieval.
