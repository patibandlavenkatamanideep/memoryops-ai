"""Transactional evidence (v2.3, P0): mutation + audit are one atomic unit of
work, the audit hash-chain cannot fork under concurrency, and global worker
health degrades gracefully instead of leaking or crashing.

These are the "teeth" behind the auditability invariant (#7): the guarantee is
that successful *and* partially-failed mutations leave the store consistent —
never a memory without its audit event, nor an audit event without its memory.
"""

from __future__ import annotations

import threading

import pytest

from app.db.entities import StoredAudit, StoredMemory
from app.evidence.hashchain import verify_chain
from app.schemas.memory import (
    CandidateMemory,
    Decision,
    MemoryType,
    Sensitivity,
    Source,
    Status,
)
from app.services.audit import AuditService
from app.services.policy_broker import PolicyOutcome
from app.services.write_service import WriteService


class _Boom(Exception):
    """Injected failure."""


def _memory(content: str = "user prefers dark mode") -> StoredMemory:
    return StoredMemory(
        tenant_id="t1",
        user_id="u1",
        memory_type=MemoryType.preference,
        content=content,
        importance=5,
        confidence=0.9,
        sensitivity=Sensitivity.low,
        status=Status.active,
        source=Source(kind="chat"),
    )


# ── rollback: mutation + audit commit together or not at all ──────────────────
def test_transaction_rolls_back_memory_and_audit(repo) -> None:
    mem = _memory()
    with pytest.raises(_Boom):
        with repo.transaction("t1", "u1"):
            repo.create_memory(mem)
            repo.add_audit(
                StoredAudit(tenant_id="t1", user_id="u1", action="memory_created", reason="x")
            )
            raise _Boom()  # crash after both writes, before commit

    # Neither side survives the rollback.
    assert repo.get_memory("t1", "u1", mem.id) is None
    assert repo.list_audit("t1", "u1") == []
    # The chain head did not advance, so the next real append still links to GENESIS.
    committed = repo.add_audit(
        StoredAudit(tenant_id="t1", user_id="u1", action="memory_created", reason="ok")
    )
    assert committed.prev_hash == "0" * 64


def test_transaction_commit_persists_both(repo) -> None:
    mem = _memory()
    with repo.transaction("t1", "u1"):
        repo.create_memory(mem)
        repo.add_audit(
            StoredAudit(tenant_id="t1", user_id="u1", action="memory_created", reason="x")
        )
    assert repo.get_memory("t1", "u1", mem.id) is not None
    assert len(repo.list_audit("t1", "u1")) == 1


# ── write service: a failing audit must not leave an orphaned memory ──────────
def test_write_service_atomic_when_audit_fails(repo, monkeypatch) -> None:
    writer = WriteService(repo, AuditService(repo))

    def _explode(_event):
        raise _Boom("audit backend down")

    monkeypatch.setattr(repo, "add_audit", _explode)

    outcome = PolicyOutcome(
        decision=Decision.SAVE,
        candidate=CandidateMemory(
            content="user prefers dark mode",
            type=MemoryType.preference,
            importance=5,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            source=Source(kind="chat"),
        ),
        reason="save",
    )

    with pytest.raises(_Boom):
        writer.commit(outcome, tenant_id="t1", user_id="u1", trace_id="tr")

    # The memory write rolled back with the audit failure — no orphan.
    assert repo.list_memories("t1", "u1") == []


# ── concurrency: parallel audited ops must form one continuous chain ──────────
def test_concurrent_audit_appends_form_one_continuous_chain(repo) -> None:
    n = 40
    ready = threading.Barrier(n)
    errors: list[Exception] = []

    def _append(i: int) -> None:
        try:
            ready.wait()  # maximize contention on the chain head
            repo.add_audit(
                StoredAudit(tenant_id="t1", user_id="u1", action="op", reason=f"r{i}")
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_append, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    events = repo.list_audit("t1", "u1", limit=1000)
    assert len(events) == n
    # No fork, no orphan, every link intact — the head lock serialized the writers.
    result = verify_chain(events)
    assert result["ok"], result
    assert result["length"] == n


def test_concurrent_appends_isolate_per_tenant_chain(repo) -> None:
    n = 20
    ready = threading.Barrier(2 * n)

    def _append(tenant: str, i: int) -> None:
        ready.wait()
        repo.add_audit(StoredAudit(tenant_id=tenant, user_id="u1", action="op", reason=str(i)))

    threads = [
        threading.Thread(target=_append, args=(tenant, i))
        for tenant in ("t1", "t2")
        for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for tenant in ("t1", "t2"):
        events = repo.list_audit(tenant, "u1", limit=1000)
        assert len(events) == n
        assert verify_chain(events)["ok"]
