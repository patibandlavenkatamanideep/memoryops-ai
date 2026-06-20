# CLAUDE_ENTERPRISE.md — MemoryOps AI Enterprise Build Guide

The authoritative product + architecture brief for MemoryOps AI: an enterprise-shaped, GPT-style
memory governance system. This is the source of truth referenced by `README.md` and `CLAUDE.md`.

## 1. Product identity

- **Name:** MemoryOps AI
- **Tagline:** Enterprise memory governance for AI assistants.
- **Positioning:** A production-shaped memory control plane for AI products.
- **Core claim:** Memory is not a database. Memory is a governed decision system that decides what
  information is valuable enough to carry into the future.

**One-line pitch:** MemoryOps AI gives AI assistants ChatGPT-style memory with enterprise controls:
typed memory capture, policy evaluation, hybrid retrieval, deletion guarantees, tenant isolation,
provenance, audit logs, observability, and user/admin control.

## 2. Core thesis

Most memory demos do `chat message → vector DB → retrieve`. MemoryOps AI models memory as a lifecycle:

```text
WRITE PATH : Message → Extractor → Evaluator/Policy Broker → Write Service → Typed Stores → Audit
READ PATH  : Message → Retriever → Ranking → Context Composer → Response LLM
BACKGROUND : Decay → Reflection → Conflict Resolver → Compression
PLANES     : Security · Governance · Observability · Evaluation · Reliability
```

The five verbs: **Capture → Store → Retrieve → Update → Forget**. Governance wraps all five.

## 3. Enterprise invariants (non-negotiable)

1. Tenant isolation
2. Deletion guarantee
3. Provenance
4. Graceful degradation
5. Policy-before-storage
6. Temporary chat (no read/write)
7. Auditability (append-only)
8. Explainability
9. Typed memory
10. Evaluation via golden set

## 4. Architecture / 5. Stack

Monorepo: `apps/web` (Next.js + TS + Tailwind), `services/api` (FastAPI), `services/worker`
(background jobs), `packages/shared`, `infra/db` (Postgres + pgvector), `infra/adr`, `evals`, `docs`.
Cache: Redis. Embeddings: provider adapter + heuristic fallback. LLM: provider adapter + heuristic
fallback. Observability: structured logs + OTel-ready spans. Deployment: Docker Compose first.

**Design rule:** architecture determines the stack. Start from mission, invariants, lifecycle,
failure modes, and verification — not tools.

## 6. Core services

- **Gateway** — attach tenant/user, check temporary_chat + settings, route read/write, return
  response with memory metadata.
- **Extractor** — extract candidate memories as JSON, classify type, assign confidence/importance,
  preserve provenance.
- **Evaluator / Policy Broker** — keep/drop/pending/block; PII/secret detection; final scoring.
  Decisions: `SAVE`, `PENDING_APPROVAL`, `BLOCK`, `DROP_LOW_UTILITY`, `MERGE_WITH_EXISTING`,
  `UPDATE_EXISTING`.
- **Write service** — dedup, merge/update, embed, write to correct store, append audit.
- **Memory stores** — working / session / long-term (pgvector) / knowledge / system.
- **Retriever** — hybrid (vector + keyword + optional graph), filtered by tenant/user/status/sensitivity.
- **Ranker** — `0.35 semantic + 0.20 keyword + 0.15 importance + 0.10 recency + 0.10 confidence +
  0.10 reinforcement`.
- **Context Composer** — compact context block, internal source IDs, no leakage.
- **Worker** — decay, archive, reflect/compress, conflict resolution, system learning.
- **Observability/audit** — created/retrieved/updated/deleted/blocked/pending/retrieval_failed/
  policy_violation/cross_tenant_test_passed/eval_passed/eval_failed.

## 7. Database

Postgres + pgvector. Tables: `tenants`, `users`, `memory_records`, `memory_audit_logs`,
`memory_feedback`, `memory_settings`. RLS-ready. See `infra/db/migrations`.

## 8. API contracts

`POST /api/chat`, `GET /api/memories`, `PATCH /api/memories/{id}`, `DELETE /api/memories/{id}`
(soft delete; never retrievable again), `GET /api/audit`, `POST /api/evals/run`.

## 14. Build phases

- Phase 0 — Design spine (docs, ADRs, schema, contracts).
- Phase 1 — Core write path (chat, extractor, policy broker, write service, dashboard).
- Phase 2 — Retrieval + context (retriever, ranker, composer, memory-used response).
- Phase 3 — Governance (delete, approve/reject, audit, temporary chat, tenant tests).
- Phase 4 — Production depth (evals, decay, reflection, conflict resolution, observability).
- Phase 5 — Submission polish.

## 18. Definition of done

Enterprise docs; Compose runs API/web/Postgres/Redis; chat captures memory; policy broker
save/block/pending; dashboard view/edit/delete; retrieval of relevant memory; deleted memory not
retrieved; temporary chat disables memory; admin dashboard with audit + metrics; evals test
invariants; README explains architecture, trade-offs, roadmap, demo. Looks like serious AI infra,
not a wrapper.
