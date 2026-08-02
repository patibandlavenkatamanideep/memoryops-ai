# ADR-009 — Memory control plane + governance UI

Status: Accepted (v0.5)

## Context
Through v0.4, every governed memory action existed only as an API or a single
read-only "Memory dashboard" table. Operators could not, from the browser,
inspect a memory's provenance, walk its audit history, approve/reject the
human-in-the-loop queue, or see *why* the policy broker decided what it decided.
The lifecycle was fully governed in code but not **operable** by a human.

v0.5 adds the browser-facing control plane. The hard requirement: surface the
lifecycle without weakening any invariant. The UI must be a thin, audited view
over the existing read/write/policy/audit paths — never a side-channel that
mutates state outside them.

## Decision
Add a control plane spanning a few additive backend routes and a set of Next.js
pages/components.

### Backend (additive only — no lifecycle behavior changed)
- `GET /api/memories/{id}` — single memory detail, tenant + user scoped. Returns
  soft-deleted rows too (for forensics) but the real `status` always travels with
  the record, so a deleted memory can never be rendered as active.
- `GET /api/memories/{id}/audit` — the per-memory audit timeline (newest first).
- `GET /api/memories/{id}/provenance` — `MemoryProvenance`: the stored `source`
  plus durable ranking signals (importance/confidence/weight/reinforcement), the
  memory's audit trail, and the governance loop-run ids that touched it. Never
  includes embeddings or secrets.
- `Repository.list_audit(..., memory_id=...)` — a new optional filter, mirrored in
  the in-memory and Postgres backends; `GET /api/audit?memory_id=` exposes it.

List, PATCH (edit/approve/reject/archive/restore), and soft-DELETE already
existed from earlier versions and are reused unchanged. Approve = `status→active`,
reject = `status→rejected`, archive = `status→archived`, restore =
`archived→active`. Each continues to emit its audit event and drive the
`MEMORY_GOVERNANCE` loop.

### Frontend
- Pages: `/memories` (filterable inventory), `/memories/[id]` (detail +
  provenance + audit timeline + inline edit), `/governance` (approval queue +
  recent policy decisions), `/audit` (tenant-wide append-only history).
- Components under `components/memories`, `components/governance`,
  `components/audit`. Every mutating control calls an audited backend route via
  the existing `lib/api.ts` client.

### Where the control plane sits
```text
browser (read views + action buttons)        ← apps/web (v0.5)
  → GET   list / detail / provenance / audit  (read paths, tenant-scoped)
  → PATCH / DELETE                            → policy/write/audit paths (unchanged)
  → policy broker stays authoritative; UI never writes around it
```

## Rules (enforced in code + tests)
- Deleted memories are never listed in the active inventory and never rendered as
  active; the `deleted` status is terminal and exposes no actions.
- Every read and every action is tenant + user scoped (invariant #1).
- Every UI action maps 1:1 to an audited backend action (invariant #7).
- Provenance/detail responses carry no embeddings, keys, or secrets.
- The policy broker remains authoritative (invariant #5); the UI only displays
  decisions it already recorded.
- Temporary-chat memories were never persisted, so they cannot appear here
  (invariant #6).

## Alternatives
- **Server components fetching at render** — rejected for now; the existing app is
  client-rendered with a thin `lib/api.ts`, and the control plane is interactive
  (filters, optimistic refresh). Kept consistent with `/loops` and `/chat`.
- **A dedicated usage/"why-used" log table** — deferred. v0.5 explains retrieval
  via the durable ranking signals already on the record plus live per-request
  scores in Chat; a persisted per-retrieval usage ledger is future work.
- **Hard delete from the UI** — rejected; deletion stays soft (ADR-005). Physical
  compaction/purge is tracked separately as a v0.6 lifecycle-worker candidate.

## Trade-offs
- Detail returns soft-deleted rows for forensics, accepting the small surface of
  showing deleted content in a governance context; mitigated by the explicit
  terminal `deleted` status and no available actions.
- "Why a memory was used" is approximate (ranking signals + loop evidence) until a
  per-retrieval usage ledger exists.

## Security considerations
- All control-plane reads and writes go through the tenant-scoped repository
  methods; no new unscoped query path is introduced.
- Provenance is metadata only — embeddings and raw secrets are never serialized.
- Demo identity (`tenant_demo`/`user_demo`) still comes from `lib/api.ts`; real
  auth/session wiring remains the deployment's responsibility.

## Amendment: status changes are validated as transitions

The control plane exposed `status` on `PATCH /api/memories/{id}` as a free
assignment over the whole `Status` enum. The handler's branch chain only named
`active` / `rejected` / `archived`, so any other value was written verbatim.

`status="deleted"` was the consequential case. It produced a row that satisfied the
*retrieval* half of the deletion guarantee (invariant #2 excludes `deleted` rows)
while violating everything the deletion workflow exists to provide:

- `deleted_at` stayed null, so retention and compaction — which key off
  `deleted_at` — never reclaimed the content;
- no tombstone was stamped, so tombstone lineage (ADR-018) could not propagate the
  deletion to derived memories;
- the audit trail recorded a generic `memory_updated`, not `memory_deleted`;
- and it succeeded **under a legal hold**, which `DELETE` correctly refuses with
  `409`. A preservation control was defeated by a route that was not attempting to
  delete.

The record ended in a limbo neither the deletion guarantee nor the preservation
guarantee covered: invisible to the user, un-compactable by the system, and still
reported as held by `/api/retention/memory/{id}`.

**Decision.** The control plane validates a *transition* — `(current, requested)` —
rather than a value. `app/services/status_transitions.py` is the single source of
truth; the route consults it before any mutation and additionally guards the
unsupported set so a widened schema cannot reopen the hole. Deletion is exclusive to
`DELETE /api/memories/{id}`, the only path performing legal-hold verification,
`deleted_at` assignment, tombstone creation, lineage propagation, deletion audit
evidence, and compaction eligibility.

`422` marks a status that `PATCH` never supports (`deleted`, `pending`, `blocked`);
`409` marks one that is legal in general but not from the current state.

**Compatibility.** The `status` field is retained and every transition the UI
actually issues (approve, reject, archive, restore) is unchanged, so the `1.x`
additive promise holds. One audit correction: `archived → active` is now
`memory_restored` rather than `memory_approved` — the previous code keyed the audit
action off the target status alone, making a restore indistinguishable from an
approval in the trail.

**Still open.** This closes the illegal-transition breach only. Governed content
editing (a `content` PATCH still bypasses the policy broker, secret scanning,
sensitivity reclassification, and leaves the old embedding attached to new content),
explicit transition endpoints, and API-level RBAC are follow-up work. The demo
identity note above is superseded by the authenticated BFF control plane.

## Amendment: the control plane's edit path is governed

The control plane exposed `content` on `PATCH /api/memories/{id}` as a direct
assignment. Editing was therefore the one write path that never met the policy
broker, so an operator UI action could introduce content the same system would
refuse at creation, silently keep a stale sensitivity label, ignore a legal hold,
and leave the previous embedding attached to the new text.

**Decision.** Content edits route through `app/services/update_service.py`. The
control plane keeps its shape — same endpoint, same fields — but the write is
governed: legal hold and revision are checked first, the proposed content is
evaluated by `PolicyBroker.evaluate_update`, sensitivity is recomputed rather than
inherited, the embedding is invalidated and regenerated, and the audit event carries
before/after hashes plus the policy decision instead of a bare `memory_updated`.

`MemoryRecord` gains `revision` and the patch body gains an optional
`expected_revision`, both additive. The UI can now surface a genuine edit conflict
rather than silently clobbering a concurrent change.

**Still open for the control plane:** explicit transition endpoints (approve /
reject / archive / restore / delete) to replace status-through-PATCH, versioned
content history and supersession, and API-level RBAC — the web-tier roles introduced
alongside the authenticated BFF are not a security boundary.
