"""Conflict scan worker — produces review candidates, never overwrites, scoped."""

from __future__ import annotations

from app.schemas.memory import Status
from app.workers.conflict_scan import ConflictScanWorker
from app.workers.lifecycle import WorkerContext
from app.workers.schemas import CONFLICT_CANDIDATE_DETECTED

from ._worker_helpers import NOW, seed_memory


def _ctx(**kw) -> WorkerContext:
    kw.setdefault("tenant_id", "t1")
    kw.setdefault("user_id", "u1")
    kw.setdefault("now", NOW)
    return WorkerContext(**kw)


def test_flags_contradiction_as_review_candidate(repo) -> None:
    a = seed_memory(repo, content="I prefer dark mode dashboards.")
    b = seed_memory(repo, content="I no longer prefer dark mode dashboards.")
    result = ConflictScanWorker(repo).run(_ctx())

    assert result.changed_count >= 1
    events = [
        e for e in repo.list_audit("t1", "u1") if e.action == CONFLICT_CANDIDATE_DETECTED
    ]
    assert events
    # Memory is unchanged — conflict scan only proposes, never overwrites.
    assert repo.get_memory("t1", "u1", a.id).content == "I prefer dark mode dashboards."
    assert repo.get_memory("t1", "u1", b.id).status == Status.active
    # Audit metadata carries ids + relations only (no raw content leakage).
    meta = events[0].metadata
    assert "relations" in meta and "conflict_with" in meta
    assert "content" not in meta


def test_no_candidate_when_no_conflict(repo) -> None:
    seed_memory(repo, content="I prefer dark mode dashboards.")
    seed_memory(repo, content="I am building a memory governance system.")
    result = ConflictScanWorker(repo).run(_ctx())
    events = [
        e for e in repo.list_audit("t1", "u1") if e.action == CONFLICT_CANDIDATE_DETECTED
    ]
    assert events == []
    assert result.changed_count == 0


def test_does_not_cross_tenant(repo) -> None:
    seed_memory(repo, tenant_id="t1", content="I prefer dark mode dashboards.")
    seed_memory(repo, tenant_id="t2", content="I no longer prefer dark mode dashboards.")
    result = ConflictScanWorker(repo).run(_ctx(tenant_id="t1"))
    # The contradicting memory lives in t2; t1 has no in-tenant conflict.
    assert result.changed_count == 0


def test_ignores_deleted_memory(repo) -> None:
    seed_memory(repo, content="I prefer dark mode dashboards.")
    seed_memory(repo, content="I no longer prefer dark mode dashboards.", status=Status.deleted)
    result = ConflictScanWorker(repo).run(_ctx())
    assert result.changed_count == 0  # deleted row is never a conflict candidate
