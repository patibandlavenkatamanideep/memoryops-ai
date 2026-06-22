"""Shared helpers for worker tests — seed StoredMemory rows deterministically."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.entities import StoredMemory
from app.db.memory_repo import InMemoryRepository
from app.schemas.memory import MemoryType, Sensitivity, Source, Status

NOW = datetime(2026, 6, 21, tzinfo=UTC)


def seed_memory(
    repo: InMemoryRepository,
    *,
    tenant_id: str = "t1",
    user_id: str = "u1",
    content: str = "I prefer dark mode dashboards.",
    importance: int = 8,
    confidence: float = 0.9,
    status: Status = Status.active,
    memory_type: MemoryType = MemoryType.preference,
    age_days: int = 0,
    metadata: dict | None = None,
    now: datetime = NOW,
) -> StoredMemory:
    created = now - timedelta(days=age_days)
    mem = StoredMemory(
        tenant_id=tenant_id,
        user_id=user_id,
        memory_type=memory_type,
        content=content,
        importance=importance,
        confidence=confidence,
        sensitivity=Sensitivity.low,
        status=status,
        source=Source(kind="chat", excerpt=content),
        metadata=metadata or {},
        created_at=created,
        updated_at=created,
    )
    if status == Status.deleted:
        mem.deleted_at = now
    return repo.create_memory(mem)
