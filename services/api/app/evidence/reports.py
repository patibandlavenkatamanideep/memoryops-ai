"""Enterprise evidence reports (v2.0, ADR-024).

Turns MemoryOps' internal governance state into security-reviewable, compliance-
friendly artifacts — all **tenant/user scoped** and content-minimizing (previews, ids,
decisions; never full secrets). Each builds on the tamper-evident audit chain so a
report is not just a claim but verifiable evidence.
"""

from __future__ import annotations

import hashlib
from collections import Counter

from ..db import governance as gov
from ..db import lineage
from ..db.repository import Repository
from .hashchain import verify_chain

_PREVIEW = 120


def _chronological(repo: Repository, tenant_id: str, user_id: str | None, **kw) -> list:
    """Audit rows oldest→newest for a scope (list_audit returns newest-first)."""
    rows = repo.list_audit(tenant_id, user_id, limit=kw.pop("limit", 1000), **kw)
    return list(reversed(rows))


def _event_view(e) -> dict:
    return {
        "id": e.id,
        "action": e.action,
        "reason": e.reason,
        "memory_id": e.memory_id,
        "trace_id": e.trace_id,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "entry_hash": e.entry_hash,
        "prev_hash": e.prev_hash,
    }


def _bundle_hash(events: list) -> str:
    h = hashlib.sha256()
    for e in events:
        h.update(e.entry_hash.encode("utf-8"))
    return h.hexdigest()


def verify_audit(repo: Repository, tenant_id: str, user_id: str | None = None) -> dict:
    """Tamper-evidence check over a tenant's audit chain (invariant #7)."""
    # The chain is per-tenant; verify the whole tenant chain (user filter would break links).
    events = _chronological(repo, tenant_id, None)
    result = verify_chain(events)
    return {"tenant_id": tenant_id, **result}


def evidence_bundle(repo: Repository, tenant_id: str, user_id: str, trace_id: str) -> dict:
    """Every audited action behind one response (`trace_id`), plus a bundle hash.

    The bundle is verifiable: each event carries its chain hash, and `chain_intact`
    reflects the tenant chain the events belong to.
    """
    scoped = [e for e in _chronological(repo, tenant_id, user_id) if e.trace_id == trace_id]
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "trace_id": trace_id,
        "event_count": len(scoped),
        "actions": dict(Counter(e.action for e in scoped)),
        "events": [_event_view(e) for e in scoped],
        "bundle_hash": _bundle_hash(scoped),
        "chain_intact": verify_audit(repo, tenant_id)["ok"],
    }


def deletion_proof(repo: Repository, tenant_id: str, user_id: str, memory_id: str) -> dict:
    """Prove a memory is forgotten: status, tombstone, compaction, non-retrievability,
    lineage, and the audited deletion path — everything a reviewer needs."""
    memory = repo.get_memory(tenant_id, user_id, memory_id)
    events = [
        _event_view(e)
        for e in _chronological(repo, tenant_id, user_id, memory_id=memory_id)
    ]
    if memory is None:
        return {
            "memory_id": memory_id, "found": False,
            "detail": "no such memory in scope (never existed or hard-purged)",
            "audit_events": events, "chain_intact": verify_audit(repo, tenant_id)["ok"],
        }
    active_ids = {m.id for m in repo.retrieve_active(tenant_id, user_id)}
    checks = {
        "status_is_deleted": memory.status.value == "deleted",
        "tombstoned": lineage.is_tombstoned(memory),
        "vector_material_cleared": bool(getattr(memory, "content", None) in (None, "")),
        "excluded_from_active_retrieval": memory.id not in active_ids,
        "has_deletion_audit": any(
            ("delet" in e["action"] or "compact" in e["action"]) for e in events
        ),
    }
    return {
        "memory_id": memory_id,
        "found": True,
        "proven": all(v for k, v in checks.items() if k != "vector_material_cleared"),
        "checks": checks,
        "audit_events": events,
        "chain_intact": verify_audit(repo, tenant_id)["ok"],
    }


def policy_report(repo: Repository, tenant_id: str, user_id: str) -> dict:
    """Aggregate the policy/lifecycle decisions recorded for a scope (audited)."""
    events = _chronological(repo, tenant_id, user_id)
    by_action = Counter(e.action for e in events)
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "total_events": len(events),
        "by_action": dict(by_action),
        "chain_intact": verify_audit(repo, tenant_id)["ok"],
    }


def lifecycle_export(repo: Repository, tenant_id: str, user_id: str, memory_id: str) -> dict:
    """A portable, content-minimized lifecycle record for one memory."""
    memory = repo.get_memory(tenant_id, user_id, memory_id)
    events = [
        _event_view(e)
        for e in _chronological(repo, tenant_id, user_id, memory_id=memory_id)
    ]
    if memory is None:
        return {"memory_id": memory_id, "found": False, "audit_timeline": events}
    content = memory.content or ""
    return {
        "memory_id": memory_id,
        "found": True,
        "memory_type": memory.memory_type.value,
        "status": memory.status.value,
        "sensitivity": memory.sensitivity.value,
        "content_preview": content[:_PREVIEW] + ("…" if len(content) > _PREVIEW else ""),
        "provenance": memory.source.kind if memory.source else None,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "governance": gov.public_governance(memory),
        "lineage": {
            "parent_memory_ids": lineage.parent_ids(memory),
            "is_derived": lineage.is_derived(memory),
            "tombstoned": lineage.is_tombstoned(memory),
        },
        "audit_timeline": events,
        "chain_intact": verify_audit(repo, tenant_id)["ok"],
    }
