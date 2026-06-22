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

### LLM extraction is advisory (v0.4)

The extractor may use an LLM provider (`app/llm/`, ADR-008) to propose candidates,
but the **policy broker remains the single authoritative decision point**. LLM
output is schema-validated and advisory only: it cannot upgrade, bypass, or
override a policy decision, and secret-like content is blocked regardless of what
a model proposes. A provider failure or invalid JSON degrades to the deterministic
heuristic and never blocks the response. Conflict detection (`detect_conflicts`)
is observability-only metadata (`conflict_detection_result`) and changes no
decision.

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

As of v0.3 each `used_memory` also carries a `score_breakdown` (the raw vector / keyword /
importance / confidence / recency / reinforcement signals behind its rank) and `memory_type` /
`source`, and the response reports a `retrieval_mode` (`hybrid` | `fallback` | `none`). This makes
ranking auditable — a reviewer can see not just *that* a memory was used, but exactly which signals
caused it to surface. See [ADR-006](../infra/adr/ADR-006-pgvector-rls-retrieval.md) and
[api-contracts.md](api-contracts.md).

## Context compression & governance order (v0.2.1)

Optional token compression (Headroom, ADR-007) runs strictly **after** governance:
policy checks, retrieval filtering, and context composition all complete first.
Compression touches only the composed, governed context block sent to the LLM —
never the raw user message and never pre-policy content — so the policy broker
always inspects raw content, and deleted / wrong-tenant / temporary-chat content
is never compressed (it is never retrieved/composed in the first place).
Explainability metadata (`used_memories` + score breakdown) is built on the
uncompressed path. See [docs/token-compression.md](token-compression.md).

## Loop governance (v0.3.1)

The governance surface is modeled as `memory.governance`. Viewing, editing,
approving, rejecting, archiving, and deleting memory emits loop events with
structured evidence and links to audit events where a governance record is
written. This keeps operational loop traces separate from append-only audit
records while making the state transition visible.

## Governance control plane (v0.5)

The governance surface is now operable from the browser. `/governance` runs the
human-in-the-loop approval queue (approve → active, reject → rejected) and shows
the policy broker's recorded decisions (SAVE / PENDING / BLOCKED / DROPPED /
UPDATED / MERGED) with their rationale. `/memories` and `/memories/[id]` expose
the full inventory, per-memory provenance, and the per-memory audit timeline;
`/audit` shows the tenant-wide append-only history. Every action maps 1:1 to an
audited backend route and the policy broker stays authoritative — the UI never
writes around it. See [governance-ui.md](governance-ui.md),
[memory-control-plane.md](memory-control-plane.md),
[ADR-009](../infra/adr/ADR-009-memory-control-plane.md), and the
[human-in-the-loop phase gate](phase-gates/phase-06-human-in-the-loop.md).

## Background lifecycle workers (v0.6)

Memory maintenance after capture is governed too. The background workers
(`services/api/app/workers/`) run **off the chat path** and emit append-only audit
evidence for every run and action: `lifecycle_worker_started` / `_completed` /
`_failed`, plus `memory_decay_applied`, `memory_archive_candidate`,
`memory_archived_by_worker`, `deletion_verification_passed` / `_failed`,
`conflict_candidate_detected`, and `reflection_candidate_detected`. Audit metadata
is content-free (ids, counts, flags only — never raw memory content or user
messages). Workers **demote, archive, flag, or propose**; they never bypass the
policy broker to create or promote active memory, and conflict/reflection output
is a *review candidate*, not an automatic change. See
[background-lifecycle-workers.md](background-lifecycle-workers.md) and
[ADR-010](../infra/adr/ADR-010-background-memory-lifecycle-workers.md).

## Retention & feedback

- `memory_feedback` captures `helpful | wrong | outdated | sensitive | not_relevant` and feeds the
  decay/reflection workers and the eval golden set.
- Retention policy, legal hold, and export are documented in [security.md](security.md) as roadmap.
