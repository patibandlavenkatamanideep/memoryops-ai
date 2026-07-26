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
    WorkerRunStatus,
)

from ._worker_helpers import seed_memory

NOW = datetime(2026, 6, 21, tzinfo=UTC)


class _CrashOnAction(InMemoryRepository):
    """In-memory repo that raises when an audit event of ``action`` is written —
    simulating a process/store failure *between* a worker's mutation and its audit."""

    def __init__(self, action: str) -> None:
        super().__init__()
        self._crash_action = action
        self.crashed = False

    def add_audit(self, event: StoredAudit) -> StoredAudit:
        if event.action == self._crash_action:
            self.crashed = True
            raise RuntimeError("injected audit failure")
        return super().add_audit(event)


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


# ── happy path still commits both sides ──────────────────────────────────────
def test_decay_commits_mutation_and_audit_together() -> None:
    repo = InMemoryRepository()
    mem = seed_memory(repo, importance=8, age_days=300)

    result = DecayWorker(repo, age_threshold_days=90, importance_step=2).run(_ctx())

    assert result.status == WorkerRunStatus.completed.value
    assert repo.get_memory("t1", "u1", mem.id).importance == 6  # applied
    assert MEMORY_DECAY_APPLIED in _actions_for(repo, mem.id)  # and audited
