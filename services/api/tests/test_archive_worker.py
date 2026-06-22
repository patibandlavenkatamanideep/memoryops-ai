"""Archive worker — archives stale memory, skips protected/recent, tenant scoped."""

from __future__ import annotations

from app.schemas.memory import Status
from app.workers.archive import ArchiveWorker
from app.workers.lifecycle import WorkerContext
from app.workers.schemas import MEMORY_ARCHIVE_CANDIDATE, MEMORY_ARCHIVED_BY_WORKER

from ._worker_helpers import NOW, seed_memory


def _ctx(**kw) -> WorkerContext:
    kw.setdefault("tenant_id", "t1")
    kw.setdefault("user_id", "u1")
    kw.setdefault("now", NOW)
    return WorkerContext(**kw)


def test_archives_stale_memory(repo) -> None:
    mem = seed_memory(repo, age_days=400)
    result = ArchiveWorker(repo, age_threshold_days=180, recent_use_days=30).run(_ctx())
    assert result.changed_count == 1
    fetched = repo.get_memory("t1", "u1", mem.id)
    assert fetched.status == Status.archived
    assert fetched.archived_at is not None
    actions = {e.action for e in repo.list_audit("t1", "u1", memory_id=mem.id)}
    assert MEMORY_ARCHIVED_BY_WORKER in actions


def test_skips_recent_memory(repo) -> None:
    mem = seed_memory(repo, age_days=10)
    result = ArchiveWorker(repo, age_threshold_days=180).run(_ctx())
    assert result.changed_count == 0
    assert repo.get_memory("t1", "u1", mem.id).status == Status.active


def test_skips_pinned_memory(repo) -> None:
    mem = seed_memory(repo, age_days=400, metadata={"pinned": True})
    result = ArchiveWorker(repo, age_threshold_days=180).run(_ctx())
    assert result.changed_count == 0
    assert repo.get_memory("t1", "u1", mem.id).status == Status.active


def test_skips_protected_memory(repo) -> None:
    mem = seed_memory(repo, age_days=400, metadata={"protected": True})
    ArchiveWorker(repo, age_threshold_days=180).run(_ctx())
    assert repo.get_memory("t1", "u1", mem.id).status == Status.active


def test_skips_recently_used_memory(repo) -> None:
    # Old by creation, but used recently → must not archive.
    used_recently = (NOW).isoformat()
    mem = seed_memory(
        repo, age_days=400, metadata={"lifecycle": {"last_used_at": used_recently}}
    )
    ArchiveWorker(repo, age_threshold_days=180, recent_use_days=30).run(_ctx())
    assert repo.get_memory("t1", "u1", mem.id).status == Status.active


def test_dry_run_proposes_candidate_without_changing(repo) -> None:
    mem = seed_memory(repo, age_days=400)
    result = ArchiveWorker(repo, age_threshold_days=180).run(_ctx(dry_run=True))
    assert result.changed_count == 1
    assert repo.get_memory("t1", "u1", mem.id).status == Status.active  # unchanged
    actions = {e.action for e in repo.list_audit("t1", "u1", memory_id=mem.id)}
    assert MEMORY_ARCHIVE_CANDIDATE in actions


def test_does_not_touch_deleted_memory(repo) -> None:
    mem = seed_memory(repo, age_days=400, status=Status.deleted)
    result = ArchiveWorker(repo, age_threshold_days=180).run(_ctx())
    assert result.scanned_count == 0
    assert repo.get_memory("t1", "u1", mem.id).status == Status.deleted


def test_is_tenant_scoped(repo) -> None:
    mine = seed_memory(repo, tenant_id="t1", age_days=400)
    other = seed_memory(repo, tenant_id="t2", age_days=400)
    ArchiveWorker(repo, age_threshold_days=180).run(_ctx(tenant_id="t1"))
    assert repo.get_memory("t1", "u1", mine.id).status == Status.archived
    assert repo.get_memory("t2", "u1", other.id).status == Status.active
