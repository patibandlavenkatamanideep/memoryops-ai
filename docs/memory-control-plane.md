# Memory Control Plane (v0.5)

The control plane is the API surface behind the [Governance UI](governance-ui.md)
for inspecting and governing individual memories. It is **additive** over the
v0.1–v0.4 lifecycle: no retrieval, write, policy, or deletion behavior changed.
See [ADR-009](../infra/adr/ADR-009-memory-control-plane.md).

## Endpoints

All endpoints are tenant + user scoped (invariant #1).

### List
`GET /api/memories?tenant_id=&user_id=&status=&memory_type=`
Returns active inventory (soft-deleted rows excluded, invariant #2). `status` and
`memory_type` are optional server-side filters.

### Detail
`GET /api/memories/{id}?tenant_id=&user_id=`
Single `MemoryRecord`. Returns soft-deleted rows too (forensics), but the real
`status` always travels with the record — callers must never present a `deleted`
row as active. `404` if not found in scope. Emits a `memory_viewed` audit event.

### Provenance
`GET /api/memories/{id}/provenance?tenant_id=&user_id=` → `MemoryProvenance`:

```jsonc
{
  "memory_id": "…",
  "source": { "kind": "chat", "excerpt": "…", "message_id": null, "conversation_id": null },
  "status": "active",
  "created_at": "…", "updated_at": "…",
  "reinforcement_count": 0,
  "importance": 5, "confidence": 0.8, "weight": 1.0,   // durable ranking signals
  "audit_trail": [ /* AuditEvent[] newest first */ ],
  "loop_run_ids": [ "…" ]                              // governance loop evidence
}
```
Provenance is metadata only — it never includes embeddings or secrets.

### Per-memory audit timeline
`GET /api/memories/{id}/audit?tenant_id=&user_id=&limit=` → `AuditEvent[]`
Newest-first lifecycle history scoped to one memory.

### Mutations (reused from earlier versions)
- `PATCH /api/memories/{id}` — edit `content`/`importance`/`confidence`, or set
  `status` to approve (`active`), reject (`rejected`), archive (`archived`), or
  restore (`active`). `404` on a deleted memory — `deleted` is terminal.
- `DELETE /api/memories/{id}` — soft delete; the row is excluded from all future
  retrieval and listing.

### Tenant-wide audit
`GET /api/audit?tenant_id=&user_id=&memory_id=&limit=` — append-only history;
`memory_id` is a new optional filter.

## Repository change

`Repository.list_audit(tenant_id, user_id=None, *, memory_id=None, limit=200)`
gains the `memory_id` filter, implemented in both the in-memory and Postgres
backends. No other repository contract changed.

## Explainability: "why a memory was used"

v0.5 explains retrieval through signals already in the system:
- **Durable ranking signals** on the record — importance, confidence, weight,
  reinforcement count (shown on provenance/detail).
- **Loop evidence** — governance loop-run ids that touched the memory.
- **Live per-request scores** — the Chat view still returns `used_memories` with a
  full `score_breakdown` (vector similarity, keyword, recency, …) per turn.

A persisted per-retrieval usage ledger (exact "used in conversation X at time T")
is intentionally **out of scope** for v0.5 and is future lifecycle work.

## Invariants upheld

1. Tenant isolation — every endpoint filters by `tenant_id` + `user_id`.
2. Deletion guarantee — deleted rows excluded from list/retrieval; detail marks
   them `deleted` and the UI never shows them as active.
3. Provenance — `source` is always present and surfaced.
5. Policy-before-storage — unchanged; the control plane never writes around it.
6. Temporary chat — never persisted, so never visible here.
7. Auditability — every action (and detail view) appends an audit event.
