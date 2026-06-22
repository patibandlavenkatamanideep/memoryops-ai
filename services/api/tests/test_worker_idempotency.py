"""Workers are idempotent and safe to retry — a second run makes no new change."""

from __future__ import annotations

from app.schemas.memory import Status
from app.workers.archive import ArchiveWorker
from app.workers.conflict_scan import ConflictScanWorker
from app.workers.decay import DecayWorker
from app.workers.deletion_verification import DeletionVerificationWorker
from app.workers.lifecycle import WorkerContext
from app.workers.runner import run_jobs

from ._worker_helpers import NOW, seed_memory


def _ctx(**kw) -> WorkerContext:
    kw.setdefault("tenant_id", "t1")
    kw.setdefault("user_id", "u1")
    kw.setdefault("now", NOW)
    return WorkerContext(**kw)


def test_decay_is_idempotent(repo) -> None:
    mem = seed_memory(repo, importance=8, age_days=300)
    first = DecayWorker(repo, age_threshold_days=90, importance_step=2).run(_ctx())
    second = DecayWorker(repo, age_threshold_days=90, importance_step=2).run(_ctx())
    assert first.changed_count == 1
    assert second.changed_count == 0  # already decayed → skipped
    assert repo.get_memory("t1", "u1", mem.id).importance == 6  # not decayed twice


def test_archive_is_idempotent(repo) -> None:
    mem = seed_memory(repo, age_days=400)
    first = ArchiveWorker(repo, age_threshold_days=180).run(_ctx())
    second = ArchiveWorker(repo, age_threshold_days=180).run(_ctx())
    assert first.changed_count == 1
    assert second.changed_count == 0  # archived rows leave the active set
    assert repo.get_memory("t1", "u1", mem.id).status == Status.archived


def test_conflict_scan_is_repeatable(repo) -> None:
    seed_memory(repo, content="I prefer dark mode dashboards.")
    seed_memory(repo, content="I no longer prefer dark mode dashboards.")
    first = ConflictScanWorker(repo).run(_ctx())
    second = ConflictScanWorker(repo).run(_ctx())
    # Re-running re-detects the same candidates without mutating memory (safe to
    # retry); the run is deterministic.
    assert first.changed_count == second.changed_count


def test_deletion_verification_is_repeatable(repo) -> None:
    seed_memory(repo, status=Status.deleted)
    first = DeletionVerificationWorker(repo).run(_ctx())
    second = DeletionVerificationWorker(repo).run(_ctx())
    assert first.error_count == 0 and second.error_count == 0
    assert first.details["verified_count"] == second.details["verified_count"]


def test_run_all_jobs_is_safe_to_retry(repo) -> None:
    seed_memory(repo, importance=8, age_days=400)
    seed_memory(repo, status=Status.deleted)
    first = run_jobs(repo, tenant_id="t1", user_id="u1", jobs=["all"], now=NOW)
    second = run_jobs(repo, tenant_id="t1", user_id="u1", jobs=["all"], now=NOW)
    assert first.ok and second.ok
    # Second pass changes nothing further (decay/archive already applied).
    assert second.changed_count == 0
