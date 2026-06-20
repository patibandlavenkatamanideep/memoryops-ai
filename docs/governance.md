# Governance — MemoryOps AI

Governance wraps the five verbs (Capture, Store, Retrieve, Update, Forget). It answers: *who* can
do *what* to memory, *why* it happened, and *how* it is proven.

## Memory lifecycle states

```text
            ┌────────── extractor ──────────┐
            ▼                                │
   (candidate) ─▶ policy broker ─▶ decision ─┤
                                             │
   SAVE             ─────────────▶ active ───┼──▶ archived (decayed/aged)
   PENDING_APPROVAL ─────────────▶ pending ──┼──▶ active (approved) / rejected
   BLOCK            ─────────────▶ blocked (never stored content; audit only)
   DROP_LOW_UTILITY ─────────────▶ (discarded; audit only)
   UPDATE_EXISTING  ─────────────▶ active (existing row updated, reinforcement++)
   MERGE_WITH_EXISTING ──────────▶ active (existing row merged)

   active ─▶ (DELETE) ─▶ deleted   [never retrievable again]
```

## Decision semantics

| Decision             | Stored? | Retrievable? | Audit action            |
|----------------------|---------|--------------|-------------------------|
| `SAVE`               | yes     | yes          | `memory_created`        |
| `PENDING_APPROVAL`   | yes     | no (pending) | `memory_pending_approval` |
| `BLOCK`              | no      | no           | `memory_blocked`        |
| `DROP_LOW_UTILITY`   | no      | no           | `memory_dropped`        |
| `UPDATE_EXISTING`    | yes     | yes          | `memory_updated`        |
| `MERGE_WITH_EXISTING`| yes     | yes          | `memory_merged`         |

## Roles (target)

- **User** — view, approve/reject, edit, archive, delete own memory; toggle settings.
- **Approver** — clear the pending queue for a tenant.
- **Admin** — tenant metrics, settings, lifecycle oversight (no covert read of raw content beyond
  policy).
- **Auditor** — read-only access to `memory_audit_logs`.

## Audit events (append-only)

`memory_created`, `memory_retrieved`, `memory_updated`, `memory_deleted`, `memory_blocked`,
`memory_dropped`, `memory_pending_approval`, `memory_approved`, `memory_rejected`,
`memory_archived`, `retrieval_failed`, `policy_violation`, `temporary_chat_skipped`,
`cross_tenant_test_passed`, `eval_passed`, `eval_failed`.

Each event records `tenant_id`, `user_id`, `memory_id` (nullable), `action`, `reason`, `metadata`,
`created_at`. Audit logs are never updated or deleted through the API.

## Explainability (invariant #8)

Every chat response carries `used_memories` (the memory IDs + reasons that shaped the answer) and
`candidate_memories` (what the extractor proposed and what the policy broker decided). The dashboard
surfaces both so a user/judge can see *why* the assistant said what it said.

## Retention & feedback

- `memory_feedback` captures `helpful | wrong | outdated | sensitive | not_relevant` and feeds the
  decay/reflection workers and the eval golden set.
- Retention policy, legal hold, and export are documented in [security.md](security.md) as roadmap.
