"""Deletion verification worker — passes when deleted memory is excluded; fails
safely (records evidence, never resurrects) if a deleted id ever leaks."""

from __future__ import annotations

from app.schemas.memory import Status
from app.workers.deletion_verification import DeletionVerificationWorker
from app.workers.lifecycle import WorkerContext
from app.workers.schemas import (
    DELETION_VERIFICATION_FAILED,
    DELETION_VERIFICATION_PASSED,
    WorkerRunStatus,
)

from ._worker_helpers import NOW, seed_memory


def _ctx(**kw) -> WorkerContext:
    kw.setdefault("tenant_id", "t1")
    kw.setdefault("user_id", "u1")
    kw.setdefault("now", NOW)
    return WorkerContext(**kw)


def test_passes_when_deleted_memory_excluded(repo) -> None:
    seed_memory(repo, content="active one", status=Status.active)
    deleted = seed_memory(repo, content="deleted one", status=Status.deleted)
    result = DeletionVerificationWorker(repo).run(_ctx())

    assert result.status == WorkerRunStatus.completed.value
    assert result.error_count == 0
    assert result.details["verified_count"] == 1
    assert result.details["leaked_count"] == 0
    # deleted id must not be reachable
    assert deleted.id not in {m.id for m in repo.retrieve_active("t1", "u1")}
    actions = {e.action for e in repo.list_audit("t1", "u1")}
    assert DELETION_VERIFICATION_PASSED in actions


def test_fails_safely_when_deleted_memory_leaks(repo) -> None:
    # Model a real leak: a genuinely deleted-status row that retrieve_active
    # wrongly returns (the regression invariant #2 must guard against). The
    # worker must record FAILED evidence and surface findings — mutating nothing.
    deleted = seed_memory(repo, content="should be gone", status=Status.deleted)

    class _LeakyRepo:
        def __init__(self, inner):
            self._inner = inner

        def list_memories(self, t, u, **kw):
            return self._inner.list_memories(t, u, **kw)

        def retrieve_active(self, t, u):
            # Bug: surfaces the deleted-status row in active retrieval.
            return [self._inner.get_memory(t, u, deleted.id)]

        def search_candidates(self, t, u, emb, **kw):
            return self._inner.search_candidates(t, u, emb, **kw)

        def add_audit(self, e):
            return self._inner.add_audit(e)

    worker = DeletionVerificationWorker(_LeakyRepo(repo))
    result = worker.run(_ctx())

    assert result.status == WorkerRunStatus.completed_with_findings.value
    assert result.error_count == 1
    actions = {e.action for e in repo.list_audit("t1", "u1")}
    assert DELETION_VERIFICATION_FAILED in actions
    # The worker never mutated data: the row is still deleted, not resurrected.
    assert repo.get_memory("t1", "u1", deleted.id).status == Status.deleted


def test_is_tenant_scoped(repo) -> None:
    seed_memory(repo, tenant_id="t1", status=Status.deleted)
    seed_memory(repo, tenant_id="t2", status=Status.deleted)
    result = DeletionVerificationWorker(repo).run(_ctx(tenant_id="t1"))
    assert result.details["deleted_count"] == 1  # only t1's deleted memory
