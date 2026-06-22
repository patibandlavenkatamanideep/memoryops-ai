"""Deletion compaction worker (v0.7, ADR-011).

Proves the compaction layer above logical deletion: soft-deleted memory past its
retention window has its content + vector material cleared, the governance
tombstone + audit trail are preserved, the purge is verified, and active/archived
memory is never touched. Tenant-scoped, idempotent, fail-closed.
"""

from __future__ import annotations

import pytest

from app.db.entities import COMPACTION_META_KEY, is_compacted
from app.schemas.memory import Status
from app.workers.deletion_compaction import DeletionCompactionWorker
from app.workers.lifecycle import WorkerContext
from app.workers.metrics import summarize_compaction_results
from app.workers.runner import run_jobs
from app.workers.schemas import (
    DELETION_COMPACTION_COMPLETED,
    DELETION_COMPACTION_FAILED,
    DELETION_COMPACTION_SKIPPED,
    DELETION_COMPACTION_STARTED,
    MEMORY_CONTENT_COMPACTED,
    MEMORY_PURGE_TOMBSTONE_PRESERVED,
    MEMORY_VECTOR_PURGE_ATTEMPTED,
    MEMORY_VECTOR_PURGE_FAILED,
    MEMORY_VECTOR_PURGE_VERIFIED,
    WorkerRunStatus,
)

from ._worker_helpers import NOW, seed_memory


def _ctx(**kw) -> WorkerContext:
    kw.setdefault("tenant_id", "t1")
    kw.setdefault("user_id", "u1")
    kw.setdefault("now", NOW)
    return WorkerContext(**kw)


def _seed_deleted(repo, *, content="secret note", embedding=(0.1, 0.2, 0.3), **kw):
    mem = seed_memory(repo, content=content, status=Status.deleted, **kw)
    mem.embedding = list(embedding)  # give it real vector material to clear
    return mem


def _actions(repo, tenant="t1"):
    return [e.action for e in repo.list_audit(tenant, "u1")]


# ── core compaction ────────────────────────────────────────────────────────────
def test_soft_deleted_memory_is_compacted(repo) -> None:
    mem = _seed_deleted(repo)
    result = DeletionCompactionWorker(repo).run(_ctx())

    assert result.status == WorkerRunStatus.completed.value
    assert result.details["compacted_count"] == 1
    assert result.details["verified_count"] == 1
    assert is_compacted(repo.get_memory("t1", "u1", mem.id))


def test_active_memory_is_never_compacted(repo) -> None:
    active = seed_memory(repo, content="keep me", status=Status.active)
    DeletionCompactionWorker(repo).run(_ctx())

    row = repo.get_memory("t1", "u1", active.id)
    assert row.status == Status.active
    assert row.content == "keep me"
    assert not is_compacted(row)


def test_archived_memory_is_not_compacted_unless_deleted(repo) -> None:
    archived = seed_memory(repo, content="archived note", status=Status.archived)
    result = DeletionCompactionWorker(repo).run(_ctx())

    assert result.details["eligible_count"] == 0
    row = repo.get_memory("t1", "u1", archived.id)
    assert row.content == "archived note"
    assert not is_compacted(row)


def test_compaction_clears_retrievable_content_and_vector(repo) -> None:
    mem = _seed_deleted(repo, content="my home address is 42 Privet Drive")
    DeletionCompactionWorker(repo).run(_ctx())

    row = repo.get_memory("t1", "u1", mem.id)
    assert row.content == ""
    assert row.normalized_content == ""
    assert row.embedding == []
    assert row.source.excerpt == ""  # sensitive provenance excerpt cleared


def test_compaction_preserves_tombstone(repo) -> None:
    mem = _seed_deleted(repo)
    DeletionCompactionWorker(repo).run(_ctx())

    row = repo.get_memory("t1", "u1", mem.id)
    # Identity + deletion metadata + provenance kind survive; status stays deleted.
    assert row.id == mem.id
    assert row.tenant_id == "t1" and row.user_id == "u1"
    assert row.status == Status.deleted
    assert row.deleted_at is not None
    assert row.source.kind == "chat"
    marker = row.metadata[COMPACTION_META_KEY]
    assert marker["compacted"] is True
    assert marker["purge_status"] == "purged"
    assert marker["compacted_at"]


def test_compaction_records_audit_evidence(repo) -> None:
    _seed_deleted(repo)
    DeletionCompactionWorker(repo).run(_ctx())

    actions = set(_actions(repo))
    assert DELETION_COMPACTION_STARTED in actions
    assert MEMORY_CONTENT_COMPACTED in actions
    assert MEMORY_VECTOR_PURGE_ATTEMPTED in actions
    assert MEMORY_VECTOR_PURGE_VERIFIED in actions
    assert MEMORY_PURGE_TOMBSTONE_PRESERVED in actions
    assert DELETION_COMPACTION_COMPLETED in actions


def test_audit_metadata_is_content_free(repo) -> None:
    _seed_deleted(repo, content="topsecret value xyz")
    DeletionCompactionWorker(repo).run(_ctx())
    for e in repo.list_audit("t1", "u1"):
        assert "topsecret" not in (e.reason or "")
        assert "topsecret" not in str(e.metadata)


def test_skipped_event_when_nothing_eligible(repo) -> None:
    seed_memory(repo, status=Status.active)
    result = DeletionCompactionWorker(repo).run(_ctx())
    assert result.details["eligible_count"] == 0
    assert DELETION_COMPACTION_SKIPPED in set(_actions(repo))


def test_retention_window_blocks_compaction(repo) -> None:
    _seed_deleted(repo)  # deleted_at == NOW → age 0 days
    result = DeletionCompactionWorker(repo, min_age_days=1).run(_ctx())
    assert result.details["eligible_count"] == 0
    assert result.details["skipped_count"] == 1


def test_dry_run_compacts_nothing(repo) -> None:
    mem = _seed_deleted(repo)
    result = DeletionCompactionWorker(repo).run(_ctx(dry_run=True))

    assert result.details["eligible_count"] == 1
    assert result.details["compacted_count"] == 0
    row = repo.get_memory("t1", "u1", mem.id)
    assert row.content != ""  # untouched
    assert not is_compacted(row)


# ── retrieval safety ─────────────────────────────────────────────────────────
def test_compacted_memory_is_unreachable(repo) -> None:
    mem = _seed_deleted(repo)
    DeletionCompactionWorker(repo).run(_ctx())

    assert mem.id not in {m.id for m in repo.retrieve_active("t1", "u1")}
    assert mem.id not in {m.id for m in repo.list_memories("t1", "u1")}
    assert mem.id not in {m.id for m, _ in repo.search_candidates("t1", "u1", [])}


def test_verification_fails_when_compacted_memory_leaks_into_candidates(repo) -> None:
    mem = _seed_deleted(repo)

    class _LeakyCandidates:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def search_candidates(self, t, u, emb, **kw):
            leaked = self._inner.get_memory(t, u, mem.id)
            base = list(self._inner.search_candidates(t, u, emb, **kw))
            if leaked and all(x.id != leaked.id for x, _ in base):
                base.append((leaked, 0.0))
            return base

    result = DeletionCompactionWorker(_LeakyCandidates(repo)).run(_ctx())

    assert result.status == WorkerRunStatus.completed_with_findings.value
    assert result.details["failed_count"] == 1
    actions = set(_actions(repo))
    assert MEMORY_VECTOR_PURGE_FAILED in actions
    assert DELETION_COMPACTION_FAILED in actions
    # Still compacted (content cleared) and never resurrected.
    row = repo.get_memory("t1", "u1", mem.id)
    assert row.status == Status.deleted


def test_verification_fails_closed_when_path_errors(repo) -> None:
    _seed_deleted(repo)

    class _BrokenVerify:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def retrieve_active(self, t, u):  # used only inside verify_purged
            raise RuntimeError("retrieval path down")

    result = DeletionCompactionWorker(_BrokenVerify(repo)).run(_ctx())
    assert result.status == WorkerRunStatus.completed_with_findings.value
    assert result.details["failed_count"] == 1
    assert MEMORY_VECTOR_PURGE_FAILED in set(_actions(repo))


# ── tenant isolation ─────────────────────────────────────────────────────────
def test_compaction_is_tenant_scoped(repo) -> None:
    a = _seed_deleted(repo, tenant_id="t1")
    b = _seed_deleted(repo, tenant_id="t2")
    DeletionCompactionWorker(repo).run(_ctx(tenant_id="t1"))

    assert is_compacted(repo.get_memory("t1", "u1", a.id))
    # tenant B untouched
    b_row = repo.get_memory("t2", "u1", b.id)
    assert not is_compacted(b_row)
    assert b_row.content != ""


def test_audit_events_are_tenant_scoped(repo) -> None:
    _seed_deleted(repo, tenant_id="t1")
    _seed_deleted(repo, tenant_id="t2")
    DeletionCompactionWorker(repo).run(_ctx(tenant_id="t1"))

    assert MEMORY_CONTENT_COMPACTED in set(_actions(repo, "t1"))
    assert MEMORY_CONTENT_COMPACTED not in set(_actions(repo, "t2"))


# ── idempotency ──────────────────────────────────────────────────────────────
def test_running_twice_does_no_further_destructive_work(repo) -> None:
    mem = _seed_deleted(repo)
    DeletionCompactionWorker(repo).run(_ctx())
    second = DeletionCompactionWorker(repo).run(_ctx())

    assert second.details["eligible_count"] == 0  # already compacted, filtered out
    assert second.details["compacted_count"] == 0
    # Tombstone unchanged and still deleted.
    row = repo.get_memory("t1", "u1", mem.id)
    assert row.status == Status.deleted
    assert is_compacted(row)


def test_retry_after_failure_completes_safely(repo) -> None:
    mem = _seed_deleted(repo)

    class _FlakyCompact:
        def __init__(self, inner):
            self._inner = inner
            self.calls = 0

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def compact_deleted_memory(self, *a, **kw):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient store error")
            return self._inner.compact_deleted_memory(*a, **kw)

    flaky = _FlakyCompact(repo)
    first = DeletionCompactionWorker(flaky).run(_ctx())
    assert first.status == WorkerRunStatus.failed.value  # caught, never raised

    second = DeletionCompactionWorker(flaky).run(_ctx())
    assert second.details["compacted_count"] == 1
    assert is_compacted(repo.get_memory("t1", "u1", mem.id))


# ── policy / deletion safety ─────────────────────────────────────────────────
def test_worker_never_resurrects_or_reactivates(repo) -> None:
    mem = _seed_deleted(repo)
    DeletionCompactionWorker(repo).run(_ctx())
    row = repo.get_memory("t1", "u1", mem.id)
    assert row.status == Status.deleted  # never moved back to active/archived


# ── runner + metrics integration ─────────────────────────────────────────────
def test_runner_invokes_deletion_compaction(repo) -> None:
    mem = _seed_deleted(repo)
    report = run_jobs(repo, tenant_id="t1", user_id="u1", jobs=["deletion_compaction"])
    assert report.ok
    assert is_compacted(repo.get_memory("t1", "u1", mem.id))


def test_compaction_metrics_summary(repo) -> None:
    _seed_deleted(repo)
    report = run_jobs(repo, tenant_id="t1", user_id="u1", jobs=["deletion_compaction"])
    metrics = summarize_compaction_results(report.results)
    assert metrics["deletion_compaction_success_count"] == 1
    assert metrics["vector_purge_verified_count"] == 1
    assert metrics["tombstone_preserved_count"] == 1


@pytest.mark.parametrize("status", [Status.active, Status.archived, Status.pending])
def test_repo_compact_rejects_non_deleted(repo, status) -> None:
    mem = seed_memory(repo, status=status)
    assert repo.compact_deleted_memory("t1", "u1", mem.id, reason="x") is None
