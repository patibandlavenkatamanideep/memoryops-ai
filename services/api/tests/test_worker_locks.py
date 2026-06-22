"""Worker leases / locks (v0.8, ADR-012) — duplicate-run prevention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.workers.locks import WorkerLeaseManager, scope_key

NOW = datetime(2026, 6, 22, tzinfo=UTC)


def _mgr(repo, owner, ttl=300):
    return WorkerLeaseManager(repo, ttl_seconds=ttl, owner=owner)


def test_scope_key_is_tenant_user() -> None:
    assert scope_key("t1", "u1") == "t1:u1"


def test_second_owner_cannot_acquire_live_lease(repo) -> None:
    a = _mgr(repo, "worker-a")
    b = _mgr(repo, "worker-b")
    assert a.acquire("t1:u1", now=NOW) is True
    # Duplicate concurrent run prevented: b cannot take a live lease.
    assert b.acquire("t1:u1", now=NOW) is False


def test_same_owner_reacquire_is_ok(repo) -> None:
    a = _mgr(repo, "worker-a")
    assert a.acquire("t1:u1", now=NOW) is True
    assert a.acquire("t1:u1", now=NOW) is True  # idempotent for the holder


def test_release_allows_reacquire(repo) -> None:
    a = _mgr(repo, "worker-a")
    b = _mgr(repo, "worker-b")
    a.acquire("t1:u1", now=NOW)
    a.release("t1:u1")
    assert b.acquire("t1:u1", now=NOW) is True


def test_expired_lease_is_reclaimable(repo) -> None:
    a = _mgr(repo, "worker-a", ttl=60)
    b = _mgr(repo, "worker-b", ttl=60)
    a.acquire("t1:u1", now=NOW)
    later = NOW + timedelta(seconds=120)  # past the 60s TTL
    assert b.acquire("t1:u1", now=later) is True  # crashed worker never deadlocks


def test_wrong_owner_release_is_noop(repo) -> None:
    a = _mgr(repo, "worker-a")
    b = _mgr(repo, "worker-b")
    a.acquire("t1:u1", now=NOW)
    b.release("t1:u1")  # not the holder → no effect
    assert b.acquire("t1:u1", now=NOW) is False
    assert repo.get_lease("t1:u1").owner == "worker-a"


def test_renew_only_by_owner(repo) -> None:
    a = _mgr(repo, "worker-a", ttl=60)
    b = _mgr(repo, "worker-b", ttl=60)
    a.acquire("t1:u1", now=NOW)
    assert b.renew("t1:u1", now=NOW) is False
    assert a.renew("t1:u1", now=NOW + timedelta(seconds=30)) is True
    assert repo.get_lease("t1:u1").expires_at == NOW + timedelta(seconds=90)
