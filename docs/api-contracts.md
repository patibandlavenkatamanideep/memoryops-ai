# API Contracts — MemoryOps AI

Canonical reference for the HTTP surface. Changes to `services/api/app/routes/**`
must update this file (enforced by the PR Invariant Evidence Gate).

> **Stable as of v1.0.** This surface follows a `1.x` additive-compatibility
> promise — existing endpoints keep their methods/paths/required fields and
> responses only gain fields. See [api-stability.md](api-stability.md).

Base URL (dev): `http://localhost:8000`. Interactive docs: `/docs`.

## Authentication & scope (v1.6, optional)
Off by default (`MEMORYOPS_AUTH_MODE=none`) — the surface below is unchanged. When
enabled (`trusted_header` or `jwt`), every `/api/*` route requires an authenticated
caller and each request's `tenant_id`/`user_id` (query string or body) must match the
authenticated principal:
- `401` — missing or invalid credential (no identity header / bad or expired JWT).
- `403` — the requested `tenant_id`/`user_id` does not match the principal.

Send identity as headers (`X-MemoryOps-Tenant`/`X-MemoryOps-User`) or a bearer JWT
(`Authorization: Bearer <token>`). Additive: no request/response *shape* changes, only
these status codes when auth is on. See [auth-adapters.md](auth-adapters.md).

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
  "economics": { "embedding_model": "", "llm_model": "", "embedding_tokens": 6,
    "context_tokens": 0, "compressed_tokens": 0, "tokens_saved": 0,
    "llm_input_tokens": 18, "estimated_cost_usd": 0.0, "cost_saved_usd": 0.0,
    "priced": false },
  "trace": { "response_id": "...", "admission_counts": { "ALLOW": 1 },
    "memories_used": [{ "memory_id": "...", "content_preview": "...", "memory_type": "preference",
      "source": { "kind": "chat" }, "stored_at": "...", "status": "active", "sensitivity": "low",
      "consent_status": "granted", "retention_status": "none",
      "admission_decision": "ALLOW", "admission_reason": "...", "retrieval_score": 0.42,
      "score_breakdown": { "vector_similarity": 0.84 } }],
    "memories_blocked": [] },
  "loop_evidence": { "memory.read": "completed", "memory.write": "completed" },
  "trace_id": "..." }
```
`decision ∈ {SAVE, PENDING_APPROVAL, BLOCK, DROP_LOW_UTILITY, UPDATE_EXISTING, MERGE_WITH_EXISTING}`.

**Context Admission Gate + Memory Usage Trace (v1.3).** A memory enters context
only if it is relevant **and** allowed. The optional `trace` block is the
permissioned, explainable memory trail behind the answer: `memories_used` (admitted)
and `memories_blocked` (retrieved but denied), each with provenance, `stored_at`,
`consent_status`, `retention_status`, and an `admission_decision ∈ {ALLOW,
BLOCK_WRONG_TENANT, BLOCK_DELETED, BLOCK_ARCHIVED, BLOCK_INACTIVE,
BLOCK_CONSENT_WITHDRAWN, BLOCK_EXPIRED, BLOCK_TOMBSTONED_ANCESTOR, BLOCK_SENSITIVE,
BLOCK_LOW_CONFIDENCE}` + `admission_reason`. `BLOCK_TOMBSTONED_ANCESTOR` (v1.4)
denies a memory whose lineage ancestry contains a deleted/tombstoned/purged
ancestor — the deletion guarantee propagated to derived artifacts; see
[docs/deletion-proof-lineage.md](deletion-proof-lineage.md), ADR-018. The gate only ever *removes* memory (defense-in-depth), is
no-throw, and audits blocked turns as `context_admission_blocked`. Toggle with
`MEMORYOPS_ADMISSION_GATE` (observe-only when off) / `MEMORYOPS_MEMORY_TRACE`.
See [docs/context-admission-gate.md](context-admission-gate.md), ADR-017.

**Economics (v1.2).** The optional `economics` block carries an *advisory* token +
cost estimate for the request. Costs are list-price estimates (never billing);
`priced=false` ⇒ the active model is unpriced (e.g. the stub provider) so costs are
`0` while token counts stay real. Override prices with `MEMORYOPS_PRICING_OVERRIDES`.
See [docs/economics.md](economics.md), ADR-016.

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

**LLM extraction (v0.4).** Candidate extraction runs through the provider-neutral
LLM layer (`app/llm/`, ADR-008), selected by `MEMORYOPS_LLM_PROVIDER` (default
`stub`; optional `openai`/`anthropic`/`gemini`). The `/api/chat` request/response
shape is unchanged: LLM output is advisory and the policy broker still decides
every `candidate_memories[].decision`. A provider failure or invalid JSON degrades
to the deterministic heuristic. New structured log events (not response fields):
`llm_provider_call`, `llm_provider_failure`, `structured_output_invalid`,
`llm_fallback_used`, `memory_extraction_structured`, `conflict_detection_result`.

## GET /api/memories
Query: `tenant_id` (req), `user_id` (req), `status` (opt), `memory_type` (opt).
Returns `MemoryRecord[]`. Excludes `deleted` by default.

## GET /api/memories/{id} (v0.5)
Query: `tenant_id` (req), `user_id` (req). Returns a single `MemoryRecord`,
tenant + user scoped. Soft-deleted rows are returned too (forensics) but always
carry `status=deleted` — callers never render them as active. `404` if not in
scope. Emits a `memory_viewed` audit event.

## GET /api/memories/{id}/provenance (v0.5)
Query: `tenant_id` (req), `user_id` (req). Returns `MemoryProvenance`:
`{ memory_id, source, status, created_at, updated_at, reinforcement_count,
importance, confidence, weight, audit_trail[], loop_run_ids[] }`. Metadata only —
never embeddings or secrets.

## GET /api/memories/{id}/audit (v0.5)
Query: `tenant_id` (req), `user_id` (req), `limit` (opt, ≤1000). Returns the
per-memory `AuditEvent[]`, newest first.

## PATCH /api/memories/{id}
Body: `{ tenant_id, user_id, content?, importance?, confidence?, status? }`.
`status=active` approves a pending memory (or restores an archived one);
`rejected` rejects; `archived` archives. `404` on a `deleted` memory — deletion is
terminal. Returns the updated `MemoryRecord`. Emits an audit event.

## DELETE /api/memories/{id}
Body: `{ tenant_id, user_id }`. Soft delete: `status=deleted`, `deleted_at=now()`,
audit `memory_deleted`. The memory is never retrievable again.

## GET /api/audit
Query: `tenant_id` (req), `user_id` (opt), `memory_id` (opt), `limit` (opt, ≤1000).
Returns `AuditEvent[]` (append-only), newest first.

## GET /api/metrics
Query: `tenant_id` (req). Returns per-tenant business counts:
`{ total_memories, by_status, audit_events, by_action }`. (Distinct from the
process-wide Prometheus surface at `GET /metrics` — see Ops.)

## POST /api/evals/run
Runs the invariant eval harness in-process. Returns
`{ total, passed, failed, pass_rate, results[] }`.

## Ops
- `GET /healthz` → `{ status, version, uptime_seconds, metrics_enabled }`
- `GET /healthz/workers` → content-free worker run history (dead-letter / failure counts)
- `GET /readyz` → `{ ready, storage, llm_provider, embeddings_provider, embedding_dim, detail }`
- `GET /metrics` → **Prometheus text exposition** (v1.1; format `0.0.4`). Process-wide,
  content-free, low-cardinality (no `tenant_id`/`user_id` labels): HTTP traffic,
  retrieval latency/mode, policy-decision rate, worker run counts. Toggle with
  `MEMORYOPS_METRICS_ENABLED` (returns `404` when disabled). See
  [docs/observability.md](observability.md), ADR-015.
- Every response carries an `x-trace-id` header.

## Loop Engineering (v0.3.1)

- `GET /api/loops` -> `LoopDefinition[]`
- `GET /api/loops/{loop_id}` -> one `LoopDefinition`
- `GET /api/loops/runs?loop_id=&trace_id=&tenant_id=&user_id=&status=` -> `LoopRun[]`
- `GET /api/loops/events?loop_run_id=&loop_id=&trace_id=&event_type=` -> `LoopEvent[]`
- `GET /api/loops/trace/{trace_id}` -> `{ trace_id, runs, events }`

Loop metadata must be structured and safe: no raw API keys, secrets, passwords,
or full user messages. Loop events can link to governance audit events through
`audit_event_id`.

## Background Lifecycle Workers (v0.6)

Workers expose **no HTTP route** — they run outside the chat request path via a
CLI / callable runner, hosted by the Railway `worker` service:

```bash
python -m app.workers.runner --tenant <t> --user <u> --job all
# --job is repeatable: decay | archive | deletion_verification | conflict_scan | reflection | all
# --dry-run reports candidates without making changes
```

`run_jobs(...)` returns a `WorkerRunReport` (`to_dict()` JSON-serializable):

- `started_at`, `completed_at`, `ok`
- `totals`: `{ scanned, changed, skipped, errors, jobs }`
- `results[]`: one `WorkerJobResult` per job — `job`, `tenant_id`, `user_id`,
  `started_at`, `completed_at`, `duration_ms`, `status`
  (`completed | completed_with_findings | skipped | failed`), `scanned_count`,
  `changed_count`, `skipped_count`, `error_count`, `audit_event_ids[]`, and a
  content-free `details` object.

The CLI prints the report JSON and exits non-zero when `ok` is `false` (a failed
job or a deletion-verification finding), so it doubles as a scheduled health
check. Worker audit metadata is structured and safe: ids, counts, and flags only —
never raw memory content or full user messages.

## Retention + Legal Hold + Consent (v0.10)

Admin/governance surface over the retention layer (ADR-013). All endpoints are
tenant + user scoped; every mutation appends a content-free audit event and reads
never return memory text. See [retention-policies.md](retention-policies.md).

| Method | Path | Body / query | Purpose |
|---|---|---|---|
| POST | `/api/retention/legal-hold` | `{tenant_id,user_id,memory_id,on,reason?}` | Place / release a fail-closed legal hold |
| POST | `/api/retention/pin` | `{tenant_id,user_id,memory_id,on}` | Pin / unpin (exempt from decay + archive) |
| POST | `/api/retention/protect` | `{tenant_id,user_id,memory_id,on}` | Protect / unprotect (exempt from auto-deletion) |
| POST | `/api/retention/consent` | `{tenant_id,user_id,memory_id,status,expires_at?}` | Record consent (`granted`/`withdrawn`/`expired`/`not_required`) |
| GET | `/api/retention/policies` | — | List retention policy packs |
| GET | `/api/retention/decisions` | `?tenant_id&user_id&policy?` | Read-only retention-decision **preview** (deletes nothing) |
| GET | `/api/retention/memory/{id}` | `?tenant_id&user_id&policy?` | Governance state + decision for one memory |

`DELETE /api/memories/{id}` now returns **HTTP 409** when the memory is under
legal hold (the blocked attempt is audited as `memory_legal_hold_delete_blocked`).
