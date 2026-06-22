# Governance UI (v0.5)

The browser-facing control plane for MemoryOps' governed memory lifecycle. It
makes the lifecycle **operable by a human** without weakening any invariant —
every view is tenant-scoped and every action is audited. See
[ADR-009](../infra/adr/ADR-009-memory-control-plane.md) and the companion
[memory-control-plane.md](memory-control-plane.md).

## Pages

| Route | Purpose |
| --- | --- |
| `/memories` | Filterable memory inventory (search + status + type). Soft-deleted rows are never listed. |
| `/memories/[id]` | Detail: content (inline edit), lifecycle actions, provenance/explainability, per-memory audit timeline. |
| `/governance` | Human-in-the-loop approval queue + recent policy-broker decisions. |
| `/audit` | Tenant-wide append-only audit history, newest first. |

## Components

- `components/memories/`
  - `MemoryTable` — inventory table; rows link to detail; inline actions.
  - `MemoryFilters` — search + status + type filters (`deleted` is intentionally
    not selectable — it is never part of the active inventory).
  - `MemoryDetailPanel` — self-fetching detail (memory + provenance + audit),
    inline content edit.
  - `MemoryProvenance` — source/provenance and the durable ranking signals that
    explain why a memory is used.
  - `MemoryActions` — approve / reject / archive / restore / delete. Each maps to
    an audited backend route; deleted memories expose no actions.
  - `statusStyles.ts` — shared status→badge styling; `deleted` is visually
    distinct and struck through.
- `components/governance/`
  - `PendingMemoryQueue` — the approval queue (approve/reject).
  - `PolicyDecisionCard` — renders one recorded policy decision (SAVE / PENDING /
    BLOCKED / DROPPED / UPDATED / MERGED) with its rationale.
- `components/audit/`
  - `AuditTimeline` — reusable append-only timeline (used on detail and `/audit`).

## Action → backend mapping

| UI action | Backend call | Audit action |
| --- | --- | --- |
| approve | `PATCH /api/memories/{id}` `status=active` | `memory_approved` |
| reject | `PATCH /api/memories/{id}` `status=rejected` | `memory_rejected` |
| archive | `PATCH /api/memories/{id}` `status=archived` | `memory_archived` |
| restore | `PATCH /api/memories/{id}` `status=active` | `memory_approved` |
| edit | `PATCH /api/memories/{id}` `content=…` | `memory_updated` |
| delete | `DELETE /api/memories/{id}` | `memory_deleted` |

## Safety properties

- **Deletion guarantee** — deleted memories never appear in the inventory and are
  never rendered as active; the terminal `deleted` status carries on the record.
- **Tenant isolation** — all reads/writes are tenant + user scoped.
- **Auditability** — every action appends an audit event; the timeline reflects it.
- **Policy authority** — the UI only displays decisions the broker already made;
  it never writes around the policy/write path.
- **No secret leakage** — provenance is metadata only; no embeddings or secrets.

## Identity

Demo identity (`tenant_demo` / `user_demo`) is provided by `apps/web/lib/api.ts`.
In production these come from auth/session; the API already scopes by
`tenant_id` + `user_id` on every route.
