"""Worker mutation + audit atomicity (invariant #7 extended to workers).

Each background worker's mutate-then-audit pair now runs inside one
``repo.transaction(...)``. If the audit write fails *after* the mutation, the
mutation must roll back too — neither side survives a partial failure. These tests
inject an audit failure on the specific action a worker emits alongside its
mutation and assert the store is untouched (no half-applied change, no orphan
evidence), while unrelated audit actions (worker started/failed) still commit.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.db.entities import StoredAudit
from app.db.memory_repo import InMemoryRepository
from app.schemas.memory import Sensitivity, Status
from app.workers.archive import ArchiveWorker
from app.workers.decay import DecayWorker
from app.workers.deletion_compaction import DeletionCompactionWorker
from app.workers.lifecycle import WorkerContext, lifecycle_meta
from app.workers.retention import RetentionWorker
from app.workers.schemas import (
    MEMORY_ARCHIVED_BY_WORKER,
    MEMORY_CONTENT_COMPACTED,
    MEMORY_DECAY_APPLIED,
    MEMORY_RETENTION_EXPIRED,
    RETENTION_DECISION_RECORDED,
    WorkerRunStatus,
)

from ._worker_helpers import seed_memory

NOW = datetime(2026, 6, 21, tzinfo=UTC)


class _CrashOnAction(InMemoryRepository):
    """In-memory repo that raises on the ``after``-th audit event of ``action`` —
    simulating a process/store failure *between* a worker's mutation and its audit.
    ``after`` lets a test crash on a *later* item in a batch (default: the first)."""

    def __init__(self, action: str, *, after: int = 1) -> None:
        super().__init__()
        self._crash_action = action
        self._after = after
        self._seen = 0
        self.crashed = False

    def add_audit(self, event: StoredAudit) -> StoredAudit:
        if event.action == self._crash_action:
            self._seen += 1
            if self._seen >= self._after:
                self.crashed = True
                raise RuntimeError("injected audit failure")
        return super().add_audit(event)


class _CrashAfterSoftDelete(InMemoryRepository):
    """In-memory repo whose ``soft_delete`` performs the deletion and *then* raises —
    simulating a failure after the mutation has occurred but before the transaction
    commits. Used to prove the soft-delete itself rolls back (not merely that it was
    skipped)."""

    def __init__(self) -> None:
        super().__init__()
        self.crashed = False

    def soft_delete(self, tenant_id: str, user_id: str, memory_id: str):
        super().soft_delete(tenant_id, user_id, memory_id)  # mutation happens
        self.crashed = True
        raise RuntimeError("injected failure after soft_delete, before commit")


def _ctx(**kw) -> WorkerContext:
    kw.setdefault("tenant_id", "t1")
    kw.setdefault("user_id", "u1")
    kw.setdefault("now", NOW)
    return WorkerContext(**kw)


def _actions_for(repo, memory_id):
    return [a.action for a in repo.list_audit("t1", "u1", memory_id=memory_id)]


# ── decay ────────────────────────────────────────────────────────────────────
def test_decay_rolls_back_mutation_when_audit_fails() -> None:
    repo = _CrashOnAction(MEMORY_DECAY_APPLIED)
    mem = seed_memory(repo, importance=8, age_days=300)

    result = DecayWorker(repo, age_threshold_days=90, importance_step=2).run(_ctx())

    assert repo.crashed
    assert result.status == WorkerRunStatus.failed.value
    got = repo.get_memory("t1", "u1", mem.id)
    assert got.importance == 8  # mutation rolled back — not decayed to 6
    assert not lifecycle_meta(got).get("decayed")  # marker rolled back too
    assert MEMORY_DECAY_APPLIED not in _actions_for(repo, mem.id)  # no orphan evidence


# ── archive ──────────────────────────────────────────────────────────────────
def test_archive_rolls_back_mutation_when_audit_fails() -> None:
    repo = _CrashOnAction(MEMORY_ARCHIVED_BY_WORKER)
    mem = seed_memory(repo, age_days=400)

    result = ArchiveWorker(repo, age_threshold_days=180).run(_ctx())

    assert repo.crashed
    assert result.status == WorkerRunStatus.failed.value
    got = repo.get_memory("t1", "u1", mem.id)
    assert got.status == Status.active  # not archived — rolled back
    assert got.archived_at is None
    assert MEMORY_ARCHIVED_BY_WORKER not in _actions_for(repo, mem.id)


# ── retention (soft-delete) ──────────────────────────────────────────────────
def test_retention_rolls_back_soft_delete_when_audit_fails() -> None:
    # The expired-outcome audit fails → the soft-delete in the same transaction
    # must roll back, leaving the memory active (deletion guarantee not tripped by
    # a half-applied delete).
    repo = _CrashOnAction(MEMORY_RETENTION_EXPIRED)
    mem = seed_memory(repo, sensitivity=Sensitivity.high, age_days=200)

    result = RetentionWorker(repo, enabled=True).run(_ctx())

    assert repo.crashed
    assert result.status == WorkerRunStatus.failed.value
    assert repo.get_memory("t1", "u1", mem.id).status == Status.active  # not deleted
    assert MEMORY_RETENTION_EXPIRED not in _actions_for(repo, mem.id)


# ── deletion compaction (destructive clear) ──────────────────────────────────
def test_compaction_rolls_back_content_clear_when_audit_fails() -> None:
    repo = _CrashOnAction(MEMORY_CONTENT_COMPACTED)
    mem = seed_memory(repo, content="secret note", status=Status.deleted)

    result = DeletionCompactionWorker(repo, min_age_days=0).run(_ctx())

    assert repo.crashed
    assert result.status == WorkerRunStatus.failed.value
    got = repo.get_memory("t1", "u1", mem.id)
    assert got.status == Status.deleted  # still deleted (never resurrected)
    assert got.content == "secret note"  # content NOT cleared — rolled back
    assert MEMORY_CONTENT_COMPACTED not in _actions_for(repo, mem.id)


# ── per-item scope: earlier items stay committed when a later one fails ───────
def test_earlier_items_stay_committed_when_a_later_item_fails() -> None:
    # Three decay-eligible memories; the audit fails on the *second* one committed.
    # Per-item transactions mean item #1 stays decayed, item #2 rolls back, and the
    # batch stops (the failure propagates) so item #3 is never touched.
    repo = _CrashOnAction(MEMORY_DECAY_APPLIED, after=2)
    for i in range(3):
        seed_memory(repo, content=f"note {i}", importance=8, age_days=300)

    result = DecayWorker(repo, age_threshold_days=90, importance_step=2).run(_ctx())

    assert repo.crashed
    assert result.status == WorkerRunStatus.failed.value
    mems = repo.list_memories("t1", "u1")
    decayed = [m for m in mems if m.importance == 6]
    # Exactly one item committed its decay before the failure; the rest are untouched.
    assert len(decayed) == 1
    assert sum(1 for m in mems if m.importance == 8) == 2
    # Exactly one decay audit survived (the committed item's).
    all_audits = [a.action for a in repo.list_audit("t1", "u1")]
    assert all_audits.count(MEMORY_DECAY_APPLIED) == 1


# ── retention: failure AFTER the delete rolls back delete + all evidence ──────
def test_retention_rolls_back_delete_and_evidence_after_mutation() -> None:
    # The soft-delete succeeds and *then* the store fails before commit. Both the
    # deletion and every decision-evidence row written earlier in the same
    # transaction must roll back — not just be skipped.
    repo = _CrashAfterSoftDelete()
    mem = seed_memory(repo, sensitivity=Sensitivity.high, age_days=200)

    result = RetentionWorker(repo, enabled=True).run(_ctx())

    assert repo.crashed
    assert result.status == WorkerRunStatus.failed.value
    assert repo.get_memory("t1", "u1", mem.id).status == Status.active  # delete undone
    actions = _actions_for(repo, mem.id)
    assert RETENTION_DECISION_RECORDED not in actions  # decision evidence rolled back
    assert MEMORY_RETENTION_EXPIRED not in actions  # outcome evidence rolled back


# ── happy path still commits both sides ──────────────────────────────────────
def test_decay_commits_mutation_and_audit_together() -> None:
    repo = InMemoryRepository()
    mem = seed_memory(repo, importance=8, age_days=300)

    result = DecayWorker(repo, age_threshold_days=90, importance_step=2).run(_ctx())

    assert result.status == WorkerRunStatus.completed.value
    assert repo.get_memory("t1", "u1", mem.id).importance == 6  # applied
    assert MEMORY_DECAY_APPLIED in _actions_for(repo, mem.id)  # and audited
