# Enterprise Evidence Layer

MemoryOps already *does* the right things — policy-before-storage, admission, deletion
proofs, audit. v2.0 ([ADR-024](../infra/adr/ADR-024-enterprise-evidence-layer.md)) makes
those things **verifiable**: a security reviewer or compliance auditor can check the
evidence, not just take the claim.

## Tamper-evident audit chain

Every audit event is linked to the previous one in its tenant's chain:

```
entry_hash = SHA-256( canonical(event) + prev_hash )
```

Any edit, deletion, insertion, or reorder breaks the chain from that point, and
`GET /api/evidence/audit/verify` proves — deterministically, offline, no secret key —
whether a tenant's trail is intact:

```jsonc
// GET /api/evidence/audit/verify?tenant_id=t1&user_id=u1
{ "tenant_id": "t1", "ok": true, "length": 42, "broken_at": null, "detail": "chain intact" }
```

If someone edits a persisted event, `ok` flips to `false` and `broken_at` names the
first bad event. This is *tamper-evidence* (detecting modification of an append-only
log), not encryption — the trail stays append-only (#7) and per-tenant scoped (#1).

## Evidence bundle per response

Every response is one `trace_id`. The bundle gathers every audited action behind that
response and hashes them into a portable artifact:

```jsonc
// GET /api/evidence/response/{trace_id}?tenant_id=…&user_id=…
{ "trace_id": "…", "event_count": 5, "actions": { "memory_retrieved": 1, "context_admission_blocked": 1, … },
  "events": [ { "action": "…", "entry_hash": "…", "prev_hash": "…" }, … ],
  "bundle_hash": "…", "chain_intact": true }
```

## Deletion proof report

For any memory, produce the evidence that it is forgotten — status, tombstone,
non-retrievability, and the audited deletion path:

```jsonc
// GET /api/evidence/deletion/{memory_id}?tenant_id=…&user_id=…
{ "memory_id": "…", "found": true, "proven": true,
  "checks": { "status_is_deleted": true, "tombstoned": true,
              "excluded_from_active_retrieval": true, "has_deletion_audit": true,
              "vector_material_cleared": false },
  "audit_events": [ … ], "chain_intact": true }
```

(`vector_material_cleared` becomes true after the compaction worker runs; it is not
required for `proven`, which reflects logical deletion.)

## Policy decision report + lifecycle export

- `GET /api/evidence/policy?tenant_id=…&user_id=…` — the decisions recorded for a
  scope, aggregated by action, over the tamper-evident chain.
- `GET /api/evidence/lifecycle/{memory_id}?tenant_id=…&user_id=…` — a portable,
  content-minimized record for one memory: type, status, sensitivity, provenance,
  governance state, lineage, and its full audit timeline.

Every report is **tenant/user scoped** and content-minimizing (previews + ids +
decisions, never full secrets).

## Admin evidence dashboard

The endpoints above are the dashboard's data source. A reviewer flow:

1. `…/audit/verify` — confirm the tenant's trail is intact (green/red).
2. `…/policy` — see the decision mix (saves / blocks / admission blocks / deletions).
3. Drill into a response with `…/response/{trace_id}` or a memory with
   `…/lifecycle/{memory_id}`.
4. For a right-to-be-forgotten request, `…/deletion/{memory_id}` is the proof to hand
   back.

Because everything is JSON over the scoped HTTP API, the dashboard can live in the
existing [results dashboard](../apps/results-dashboard/) or any admin UI without new
server surface.

## Limits

- Tamper-**evidence**, not tamper-**proofing**: a writer who can rewrite the whole
  chain (full DB control) can forge a consistent one. Pin the head hash externally
  (WORM store / notary) for stronger guarantees.
- The chain is per-tenant; cross-tenant global notarization is out of scope here.
