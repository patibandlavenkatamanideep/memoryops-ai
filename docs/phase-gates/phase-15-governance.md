# Phase 15 — Governance & Compliance

**Question:** Audit trails, explainability, data residency, deletion.

## MemoryOps mapping
Typed lifecycle states with approve/reject/edit/archive/delete; append-only audit;
provenance on every memory; explainable `used_memories` on every response;
soft-delete guarantee that deleted memory is never retrieved.

## Gate (must be true to pass)
- Every memory has non-null provenance (`source`).
- Every lifecycle action is audited.
- Deleted memory is excluded from all reads.
- Responses can report which memories shaped them.

## Evidence
- `services/api/app/services/{write_service,audit}.py`
- `services/api/app/routes/memories.py` (approve/reject/archive/delete)
- `services/api/tests/test_deletion.py`
- [docs/governance.md](../governance.md)
- [ADR-005 deletion guarantee](../../infra/adr/ADR-005-deletion-guarantee.md)

## Deployment governance (v0.3.2)
Deployment is a single, auditable target — **Railway only**, one project, config
as code in `railway/`. No Vercel or ad-hoc host. This keeps the data-residency
and access story in one place; see
[phase-13-infrastructure.md](phase-13-infrastructure.md) and
[docs/deployment/railway.md](../deployment/railway.md).

## Gaps to close (→ later)
- Retention/legal-hold/export (DSAR), regional residency, crypto-shred worker.

## Status: ✅ Implemented (retention/residency are roadmap)
