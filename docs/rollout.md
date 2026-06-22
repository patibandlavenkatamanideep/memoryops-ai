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

## Phase 5 (cont.) — Worker runtime + scheduled orchestration ✅ (v0.8)
The lifecycle jobs become operable: a lease/lock prevents duplicate concurrent
runs, a retry/backoff policy absorbs transient faults, exhausted retries
dead-letter, run history is persisted, and `GET /healthz/workers` exposes health.
A thin scheduler drives the orchestrator over explicit `"tenant:user"` scopes;
`services/worker/main.py` now runs the real lifecycle workers (superseding the
legacy `jobs.py`). New migration `006_worker_runtime.sql`. See
[worker-runtime.md](worker-runtime.md),
[phase-gates/phase-14-worker-runtime-orchestration.md](phase-gates/phase-14-worker-runtime-orchestration.md),
[ADR-012](../infra/adr/ADR-012-worker-runtime-orchestration.md).

## Phase 6 — Public results dashboard + evidence explorer ✅ (v0.9)
A read-only public evidence/demo dashboard ([`apps/results-dashboard/`](../apps/results-dashboard))
makes MemoryOps understandable and inspectable: overview, version timeline,
memory lifecycle, deletion-compaction proof, worker runtime results, audit
evidence, validation results, and honest limitations. It is **demo-only** —
static demo JSON, no live DB, no secrets, no auth, no writes — and runs on
Streamlit, isolated from the core API. The Next.js app (`apps/web`) remains the
official product / governance UI; deployment stays Railway-only (no Vercel). See
[results-dashboard.md](results-dashboard.md).

## Phase 7 — Retention + legal hold + consent-aware memory ✅ (v0.10)
A retention layer on top of the deletion pipeline: named **retention policy packs**
(sensitivity tier → window) drive a `retention` worker that soft-deletes expired /
consent-revoked memory (OFF by default, with an admin-readable decision preview);
**legal hold** is a fail-closed override that blocks all forgetting (decay,
archive, retention, compaction) and the API delete route (HTTP 409); **consent**
withdrawal/expiry makes memory eligible for the normal soft-delete → verification
→ compaction path. Governance state is metadata-driven (new migration
`007_retention_legal_hold_consent.sql`) and every action is audited. Honest scope:
legal hold is a *preservation* control, not crypto-shred. See
[retention-policies.md](retention-policies.md),
[phase-gates/phase-15-governance.md](phase-gates/phase-15-governance.md),
[ADR-013](../infra/adr/ADR-013-retention-legal-hold-consent.md).

## Phase 8 — Assistant SDK + integration examples ✅ (v0.11)
A typed Python SDK ([`packages/memoryops-sdk/`](../packages/memoryops-sdk)) wraps
the governed HTTP API (chat, memories, retention/legal-hold/consent, audit,
metrics, loops, health) and injects the tenant/user scope on every call. The
**server stays authoritative** for all governance — the SDK adds none of its own.
Ships with runnable examples (quickstart, FastAPI integration, RAG assistant,
agent memory), typed errors (`LegalHoldError`/`NotFoundError`/`APIError`), and an
injectable `httpx.Client` so it is tested against the real app in-process.
Additive only — no `services/api` changes. See
[assistant-sdk.md](assistant-sdk.md),
[ADR-014](../infra/adr/ADR-014-assistant-sdk.md).

## Phase 9 — Interactive playground + hosted demo ✅ (v0.12)
An interactive public **Playground** ([`apps/playground/`](../apps/playground))
that *drives the real governed pipeline in-process* — capture → ask → govern
(legal hold / consent / delete / run lifecycle workers) → watch the audit trace
and assistant behavior change live. **Safe to host:** a fresh in-memory store per
browser session — no database, no auth, no secrets, no network (stub LLM +
embeddings), no real user data; it calls the same `services/api` governance code
the product uses (not a reimplementation). Additive only — no `services/api`
changes. The v0.9 results dashboard stays the read-only **evidence** view; the
playground is the public **entry point**. Hostable on Streamlit Community Cloud or
as an optional Railway demo service (not one of the five core services; no Vercel).
Screenshots/GIF + the hosted link are the operator-run final step. See
[playground.md](playground.md), [images/playground/](images/playground/).

## Phase 10 — Production-ready governed memory runtime ✅ (v1.0)
The stable public release. The governed lifecycle, its seven enforced invariants,
and the security/governance/reliability/observability/evaluation planes are
implemented, tested, and operable. The public HTTP API and Python SDK are declared
**stable** under a `1.x` additive-compatibility promise; package versions are
`1.0.0`. Adds release-readiness docs — a consolidated
[limitations](limitations.md) page, a [production-readiness](production-readiness.md)
map (invariant → where enforced; production-capable vs demo-only), an
[api-stability](api-stability.md) contract, and a top-level
[CHANGELOG](../CHANGELOG.md). v1.0 is stabilization + documentation: **no behavior
changes vs v0.12**.

## Public roadmap

| Version | Scope | Status |
|---------|-------|--------|
| v0.7 | Physical deletion compaction + vector purge verification | ✅ Done |
| v0.8 | Worker runtime + scheduled lifecycle orchestration | ✅ Done |
| v0.9 | Public results dashboard + evidence explorer | ✅ Done |
| v0.10 | Retention policies + legal hold + consent-aware memory | ✅ Done |
| v0.11 | Assistant SDK + integration examples | ✅ Done |
| v0.12 | Interactive playground + hosted demo + public screenshots | ✅ Done |
| v1.0 | Production-ready governed memory runtime | ✅ Done |

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
