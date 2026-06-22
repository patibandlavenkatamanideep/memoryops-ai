# Phase 06 — Human-in-the-Loop (Memory Control Plane)

**Question:** Can a human inspect, approve, correct, and govern memory from a UI —
without bypassing any invariant?

> Companion to [phase-06-memory-architecture.md](phase-06-memory-architecture.md)
> (the storage/lifecycle gate) and [phase-15-governance.md](phase-15-governance.md)
> (audit/explainability/deletion). This gate covers the **operability** layer added
> in v0.5.

## MemoryOps mapping
A browser control plane (v0.5) over the existing governed lifecycle: view and
filter memories, open detail with provenance and a per-memory audit timeline,
edit content, approve/reject the pending queue, archive/restore, soft-delete, and
read the policy broker's recorded decisions. Every action maps 1:1 to an audited
backend route; the policy broker stays authoritative. See
[ADR-009](../../infra/adr/ADR-009-memory-control-plane.md),
[governance-ui.md](../governance-ui.md), and
[memory-control-plane.md](../memory-control-plane.md).

## Gate (must be true to pass)
- A human can approve/reject pending memories from the UI, and each is audited.
- A human can edit, archive/restore, and soft-delete memories; each is audited.
- Detail exposes provenance (`source`) and the per-memory audit timeline.
- Policy decisions are visible with their rationale; the UI never writes around
  the policy/write path.
- Deleted memories are never shown as active inventory; `deleted` is terminal.
- Every control-plane read and action is tenant + user scoped.

## Evidence
- `apps/web/app/{memories,memories/[id],governance,audit}/page.tsx`
- `apps/web/components/{memories,governance,audit}/*`
- `services/api/app/routes/memories.py` (detail, `/audit`, `/provenance`)
- `services/api/app/routes/audit.py` (`memory_id` filter)
- `services/api/tests/test_governance_api.py`
- [docs/governance-ui.md](../governance-ui.md),
  [docs/memory-control-plane.md](../memory-control-plane.md)

## Gaps to close (→ later)
- Per-retrieval usage ledger for exact "why used" attribution.
- Real auth/session identity (demo identity comes from `lib/api.ts` today).
- Bulk actions and pagination for large inventories.

## Status: ✅ Implemented (usage ledger + auth are roadmap)
