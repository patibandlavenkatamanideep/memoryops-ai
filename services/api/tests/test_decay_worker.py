"""Decay worker — changes only eligible memory, never deleted, tenant scoped."""

from __future__ import annotations

from app.schemas.memory import Status
from app.workers.decay import DecayWorker
from app.workers.lifecycle import WorkerContext
from app.workers.schemas import MEMORY_DECAY_APPLIED

from ._worker_helpers import NOW, seed_memory


def _ctx(**kw) -> WorkerContext:
    kw.setdefault("tenant_id", "t1")
    kw.setdefault("user_id", "u1")
    kw.setdefault("now", NOW)
    return WorkerContext(**kw)


def test_decays_old_memory(repo) -> None:
    mem = seed_memory(repo, importance=8, age_days=200)
    result = DecayWorker(repo, age_threshold_days=90, importance_step=2).run(_ctx())

    assert result.changed_count == 1
    assert repo.get_memory("t1", "u1", mem.id).importance == 6
    actions = {e.action for e in repo.list_audit("t1", "u1", memory_id=mem.id)}
    assert MEMORY_DECAY_APPLIED in actions


def test_decays_low_confidence_memory(repo) -> None:
    mem = seed_memory(repo, importance=5, confidence=0.1, age_days=1)
    result = DecayWorker(repo, age_threshold_days=90, min_confidence=0.3).run(_ctx())
    assert result.changed_count == 1
    assert repo.get_memory("t1", "u1", mem.id).importance == 3


def test_skips_fresh_high_confidence_memory(repo) -> None:
    mem = seed_memory(repo, importance=8, confidence=0.9, age_days=1)
    result = DecayWorker(repo, age_threshold_days=90).run(_ctx())
    assert result.changed_count == 0
    assert result.skipped_count == 1
    assert repo.get_memory("t1", "u1", mem.id).importance == 8


def test_does_not_modify_deleted_memory(repo) -> None:
    mem = seed_memory(repo, importance=8, age_days=300, status=Status.deleted)
    result = DecayWorker(repo, age_threshold_days=90).run(_ctx())
    assert result.scanned_count == 0
    assert result.changed_count == 0
    fetched = repo.get_memory("t1", "u1", mem.id)
    assert fetched.status == Status.deleted
    assert fetched.importance == 8


def test_respects_importance_floor(repo) -> None:
    mem = seed_memory(repo, importance=1, age_days=300)
    result = DecayWorker(repo, age_threshold_days=90, importance_floor=1).run(_ctx())
    assert result.changed_count == 0
    assert repo.get_memory("t1", "u1", mem.id).importance == 1


def test_is_tenant_scoped(repo) -> None:
    mine = seed_memory(repo, tenant_id="t1", user_id="u1", importance=8, age_days=300)
    other = seed_memory(repo, tenant_id="t2", user_id="u1", importance=8, age_days=300)
    DecayWorker(repo, age_threshold_days=90).run(_ctx(tenant_id="t1", user_id="u1"))
    assert repo.get_memory("t1", "u1", mine.id).importance == 6
    assert repo.get_memory("t2", "u1", other.id).importance == 8  # untouched
