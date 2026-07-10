"""Tamper-evident audit hash chain (v2.0, ADR-024).

Each audit event is linked to the previous one in its tenant's chain:

    entry_hash = SHA-256( canonical(event_fields) + prev_hash )

Any edit, insertion, deletion, or reordering breaks the chain from that point on, so
`verify_chain` can prove — deterministically, offline, with no secret key — that an
audit trail is intact. This is a *tamper-evidence* control (detects modification of an
append-only log), not encryption or a signature: it does not stop a writer who can
recompute the whole chain, which is why the trail stays append-only (invariant #7) and
per-tenant scoped (invariant #1).
"""

from __future__ import annotations

import hashlib
import json

GENESIS = "0" * 64


def canonical_payload(event) -> str:
    """Stable JSON of the immutable event fields (excludes the hashes themselves)."""
    return json.dumps(
        {
            "id": event.id,
            "tenant_id": event.tenant_id,
            "user_id": event.user_id,
            "memory_id": event.memory_id,
            "action": event.action,
            "reason": event.reason,
            "trace_id": event.trace_id,
            "metadata": event.metadata,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        },
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )


def compute_entry_hash(event, prev_hash: str) -> str:
    h = hashlib.sha256()
    h.update(canonical_payload(event).encode("utf-8"))
    h.update((prev_hash or GENESIS).encode("utf-8"))
    return h.hexdigest()


def verify_chain(events: list) -> dict:
    """Reconstruct the chain from its hash links and report integrity.

    Order is recovered from `prev_hash`/`entry_hash` (not timestamps), so it is robust
    to same-microsecond ties. Returns `{ ok, length, broken_at, detail }`; `broken_at`
    names the first event that fails to link or whose content hash doesn't match, and a
    leftover (orphaned/inserted) event also fails the check.
    """
    total = len(events)
    if total == 0:
        return {"ok": True, "length": 0, "broken_at": None, "detail": "empty chain"}
    by_prev: dict[str, list] = {}
    for e in events:
        by_prev.setdefault(e.prev_hash, []).append(e)

    prev = GENESIS
    walked = 0
    while prev in by_prev:
        candidates = by_prev[prev]
        if len(candidates) != 1:
            return {
                "ok": False, "length": total, "broken_at": candidates[0].id,
                "detail": "chain fork — more than one event links to the same predecessor",
            }
        event = candidates[0]
        expected = compute_entry_hash(event, prev)
        if event.entry_hash != expected:
            return {
                "ok": False, "length": total, "broken_at": event.id,
                "detail": "content hash mismatch (event was edited)",
            }
        walked += 1
        prev = event.entry_hash
    if walked != total:
        return {
            "ok": False, "length": total, "broken_at": None,
            "detail": f"only {walked}/{total} events form an unbroken chain (missing/inserted rows)",
        }
    return {"ok": True, "length": total, "broken_at": None, "detail": "chain intact"}
