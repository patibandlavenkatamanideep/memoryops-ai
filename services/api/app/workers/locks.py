"""Worker leases (locks) for the scheduled runtime (v0.8, ADR-012).

A lease is a TTL'd mutual-exclusion token keyed by the scope being processed
(``"tenant:user"``). It prevents *duplicate concurrent runs* of the same scope
across replicas: only the worker that holds a live lease processes that scope; a
second worker that fails to acquire skips it. Because leases expire, a crashed
worker never deadlocks a scope — the lease is reclaimable after its TTL.

The atomicity lives in the repository (`try_acquire_lease`): in-memory checks the
live owner; Postgres uses `INSERT … ON CONFLICT … WHERE expired/own`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..db.repository import Repository


def scope_key(tenant_id: str, user_id: str) -> str:
    """Canonical lease key for a (tenant, user) scope."""
    return f"{tenant_id}:{user_id}"


class WorkerLeaseManager:
    def __init__(self, repo: Repository, *, ttl_seconds: int, owner: str) -> None:
        self._repo = repo
        self._ttl = timedelta(seconds=ttl_seconds)
        self._owner = owner

    @property
    def owner(self) -> str:
        return self._owner

    def acquire(self, key: str, *, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        return self._repo.try_acquire_lease(
            key, self._owner, now=now, expires_at=now + self._ttl
        )

    def renew(self, key: str, *, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        return self._repo.renew_lease(key, self._owner, expires_at=now + self._ttl)

    def release(self, key: str) -> None:
        self._repo.release_lease(key, self._owner)
