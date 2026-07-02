"""Tombstone lineage — deletion that propagates through derived artifacts (v1.4).

The deletion guarantee (invariant #2) is easy for a single row and hard once a
memory has *derived* artifacts: a summary consolidated from it, a compressed
context built from that summary, a reflection memory, and so on. Deleting the
source row is not enough if a derived artifact still carries the deleted
information into context.

This module tracks lineage so deletion can propagate. Like governance state
(``app/db/governance.py``) and the compaction tombstone
(``entities.apply_compaction``), lineage lives content-free in the memory's
``metadata`` jsonb, so both repository backends persist it and it is auditable.

Layout (under ``metadata``)::

    metadata = {
      "lineage": {
        "parent_memory_ids": [str, ...],   # direct sources this was derived from
        "lineage_root_id": str | None,     # ultimate ancestor (for fast grouping)
        "source_event_id": str | None,     # originating audit/loop event id
        "tombstoned": bool,                # explicit tombstone (set on delete)
        "tombstoned_at": iso | None,
        "tombstone_reason": str | None,
      },
    }

**Fail-closed rule.** A derived artifact may not enter context if *any* ancestor
in its lineage is tombstoned — where an ancestor counts as tombstoned when it is
soft-deleted (``status='deleted'``), carries an explicit tombstone marker, or can
no longer be found (purged / unknown id). "Can't prove it's safe" ⇒ block. The
Context Admission Gate enforces this via :func:`ancestry_tombstone` (ADR-017/018).

Invariant alignment: lineage only ever makes the system *more* conservative — it
blocks a derived artifact, never resurrects or promotes memory, and never bypasses
the policy broker (#5).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from ..schemas.memory import Status
from .entities import StoredMemory

LINEAGE_META_KEY = "lineage"

# Safety cap on ancestry traversal (defends against cycles / pathological depth).
_MAX_ANCESTRY_NODES = 256


def _lin(memory: StoredMemory) -> dict:
    meta = memory.metadata.get(LINEAGE_META_KEY)
    return dict(meta) if isinstance(meta, dict) else {}


def _write(memory: StoredMemory, lin: dict) -> None:
    # Copy-on-write so callers never mutate a shared dict in place.
    memory.metadata = dict(memory.metadata)
    memory.metadata[LINEAGE_META_KEY] = lin


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.isoformat()


# ── reading lineage ───────────────────────────────────────────────────────────
def parent_ids(memory: StoredMemory) -> list[str]:
    """Direct source memory ids this memory was derived from ([] for originals)."""
    raw = _lin(memory).get("parent_memory_ids")
    return [str(x) for x in raw] if isinstance(raw, list) else []


def lineage_root_id(memory: StoredMemory) -> str | None:
    val = _lin(memory).get("lineage_root_id")
    return val if isinstance(val, str) and val else None


def source_event_id(memory: StoredMemory) -> str | None:
    val = _lin(memory).get("source_event_id")
    return val if isinstance(val, str) and val else None


def is_derived(memory: StoredMemory) -> bool:
    """True when this memory has at least one recorded parent."""
    return bool(parent_ids(memory))


def is_tombstoned(memory: StoredMemory) -> bool:
    """True when a memory carries an explicit tombstone marker OR is soft-deleted.

    Soft-deletion is the canonical tombstone; the explicit marker adds an audited
    ``tombstoned_at``/reason and lets the ancestry check stay independent of how a
    row was deleted (API route vs. worker vs. direct ``soft_delete``).
    """
    return bool(_lin(memory).get("tombstoned")) or memory.status is Status.deleted


# ── writing lineage ───────────────────────────────────────────────────────────
def set_lineage(
    memory: StoredMemory,
    *,
    parent_ids: list[str],
    lineage_root_id: str | None = None,
    source_event_id: str | None = None,
) -> None:
    """Record that ``memory`` was derived from ``parent_ids``.

    If ``lineage_root_id`` is not given it defaults to the sole parent (a common
    single-source derivation) or is left ``None`` for multi-source artifacts.
    """
    lin = _lin(memory)
    parents = [str(p) for p in parent_ids]
    lin["parent_memory_ids"] = parents
    root = lineage_root_id or (parents[0] if len(parents) == 1 else None)
    lin["lineage_root_id"] = root
    if source_event_id is not None:
        lin["source_event_id"] = source_event_id
    _write(memory, lin)


def derived_metadata(
    *,
    parent_ids: list[str],
    lineage_root_id: str | None = None,
    source_event_id: str | None = None,
    base: dict | None = None,
) -> dict:
    """Build a ``metadata`` dict for a *new* derived memory (e.g. a reflection).

    Convenience for authoring paths that construct a memory before persisting it.
    """
    meta = dict(base or {})
    parents = [str(p) for p in parent_ids]
    root = lineage_root_id or (parents[0] if len(parents) == 1 else None)
    lineage: dict = {"parent_memory_ids": parents, "lineage_root_id": root}
    if source_event_id is not None:
        lineage["source_event_id"] = source_event_id
    meta[LINEAGE_META_KEY] = lineage
    return meta


def set_tombstone(
    memory: StoredMemory, *, on: bool = True, reason: str | None = None,
    now: datetime | None = None,
) -> None:
    """Stamp/clear the explicit tombstone marker (called on deletion)."""
    now = now or datetime.now(UTC)
    lin = _lin(memory)
    lin["tombstoned"] = bool(on)
    lin["tombstoned_at"] = _iso(now) if on else None
    lin["tombstone_reason"] = reason if on else None
    _write(memory, lin)


# ── ancestry resolution (fail-closed) ─────────────────────────────────────────
def ancestry_tombstone(
    memory: StoredMemory,
    lookup: Callable[[str], StoredMemory | None],
) -> str | None:
    """Return the id of a tombstoned ancestor, or ``None`` if the lineage is clean.

    Walks the *parent* lineage transitively (the memory itself is not checked here
    — the gate checks the candidate's own status separately). ``lookup`` resolves a
    memory id to its stored row (must be able to return soft-deleted rows). A
    missing ancestor is treated as tombstoned (fail-closed). Cycle- and depth-safe
    via a visited set and a node cap.
    """
    seen: set[str] = set()
    stack: list[str] = list(parent_ids(memory))
    while stack:
        if len(seen) > _MAX_ANCESTRY_NODES:
            # Pathological lineage — refuse to admit rather than loop (fail-closed).
            return "lineage_too_deep"
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        ancestor = lookup(pid)
        if ancestor is None:
            # Purged or unknown ancestor — cannot prove it is safe.
            return pid
        if is_tombstoned(ancestor):
            return pid
        stack.extend(parent_ids(ancestor))
    return None
