# API Contracts — MemoryOps AI

Canonical reference for the HTTP surface. Changes to `services/api/app/routes/**`
must update this file (enforced by the PR Invariant Evidence Gate).

Base URL (dev): `http://localhost:8000`. Interactive docs: `/docs`.

## POST /api/chat
Write + read path for a turn.

Request:
```json
{ "tenant_id": "tenant_demo", "user_id": "user_demo",
  "message": "Remember that I prefer enterprise-style explanations.",
  "temporary_chat": false, "conversation_id": null }
```
Response:
```json
{ "assistant_message": "...",
  "used_memories": [{ "memory_id": "...", "content": "...", "memory_type": "preference",
    "score": 0.42, "reason": "...",
    "score_breakdown": { "vector_similarity": 0.84, "keyword_score": 0.50,
      "importance_score": 0.60, "confidence": 0.92, "recency": 0.99, "reinforcement": 0.0 },
    "source": { "kind": "chat", "excerpt": "..." } }],
  "candidate_memories": [{ "content": "...", "decision": "SAVE", "type": "procedural",
    "confidence": 0.92, "importance": 8, "sensitivity": "low", "reason": "...", "memory_id": "..." }],
  "audit_event_ids": ["..."], "temporary_chat": false,
  "retrieval_mode": "hybrid",
  "loop_evidence": { "memory.read": "completed", "memory.write": "completed" },
  "trace_id": "..." }
```
`decision ∈ {SAVE, PENDING_APPROVAL, BLOCK, DROP_LOW_UTILITY, UPDATE_EXISTING, MERGE_WITH_EXISTING}`.

**Retrieval (v0.3).** `retrieval_mode ∈ {hybrid, fallback, none}` — `hybrid` blends
pgvector cosine similarity with keyword overlap; `fallback` is keyword-only after
an embedding failure (graceful degradation, invariant #4); `none` when memory was
bypassed (temporary chat / memory disabled). `score_breakdown` reports the raw,
normalized [0,1] component signals behind `score`, which is their weighted sum:

```text
score = 0.35·vector_similarity + 0.20·keyword_score + 0.15·importance_score
      + 0.10·confidence + 0.10·recency + 0.10·reinforcement
```

Changing these weights or fields requires updating this file or
docs/architecture.md (enforced by the PR Invariant Evidence Gate).

## GET /api/memories
Query: `tenant_id` (req), `user_id` (req), `status` (opt), `memory_type` (opt).
Returns `MemoryRecord[]`. Excludes `deleted` by default.

## PATCH /api/memories/{id}
Body: `{ tenant_id, user_id, content?, importance?, confidence?, status? }`.
`status=active` approves a pending memory; `rejected` rejects; `archived` archives.
Returns the updated `MemoryRecord`. Emits an audit event.

## DELETE /api/memories/{id}
Body: `{ tenant_id, user_id }`. Soft delete: `status=deleted`, `deleted_at=now()`,
audit `memory_deleted`. The memory is never retrievable again.

## GET /api/audit
Query: `tenant_id` (req), `user_id` (opt), `limit` (opt, ≤1000).
Returns `AuditEvent[]` (append-only), newest first.

## GET /api/metrics
Query: `tenant_id` (req). Returns counts:
`{ total_memories, by_status, audit_events, by_action }`.

## POST /api/evals/run
Runs the invariant eval harness in-process. Returns
`{ total, passed, failed, pass_rate, results[] }`.

## Ops
- `GET /healthz` → `{ status, version }`
- `GET /readyz` → `{ ready, storage, llm_provider, embeddings_provider, embedding_dim, detail }`
- Every response carries an `x-trace-id` header.

## Loop Engineering (v0.2.2)

- `GET /api/loops` -> `LoopDefinition[]`
- `GET /api/loops/{loop_id}` -> one `LoopDefinition`
- `GET /api/loops/runs?loop_id=&trace_id=&tenant_id=&user_id=&status=` -> `LoopRun[]`
- `GET /api/loops/events?loop_run_id=&loop_id=&trace_id=&event_type=` -> `LoopEvent[]`
- `GET /api/loops/trace/{trace_id}` -> `{ trace_id, runs, events }`

Loop metadata must be structured and safe: no raw API keys, secrets, passwords,
or full user messages. Loop events can link to governance audit events through
`audit_event_id`.
