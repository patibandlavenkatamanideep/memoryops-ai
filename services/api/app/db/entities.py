"""Internal storage entities shared by repository implementations.

Distinct from the API schemas: these carry the embedding and bookkeeping fields
the store needs but the API never returns.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..schemas.memory import MemoryRecord, MemoryType, Sensitivity, Source, Status


def _now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class StoredMemory:
    tenant_id: str
    user_id: str
    memory_type: MemoryType
    content: str
    importance: int
    confidence: float
    sensitivity: Sensitivity
    status: Status
    source: Source
    embedding: list[float] = field(default_factory=list)
    normalized_content: str = ""
    metadata: dict = field(default_factory=dict)
    weight: float = 1.0
    reinforcement_count: int = 0
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    archived_at: datetime | None = None
    deleted_at: datetime | None = None

    def to_schema(self) -> MemoryRecord:
        return MemoryRecord(
            id=self.id,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            memory_type=self.memory_type,
            content=self.content,
            importance=self.importance,
            confidence=self.confidence,
            sensitivity=self.sensitivity,
            status=self.status,
            source=self.source,
            metadata=self.metadata,
            weight=self.weight,
            reinforcement_count=self.reinforcement_count,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


# ── Deletion compaction (v0.7, ADR-011) ──────────────────────────────────────
# Where the content-free compaction tombstone lives on a memory's metadata.
COMPACTION_META_KEY = "compaction"


def is_compacted(memory: StoredMemory) -> bool:
    """True once a deleted memory's content + vector material have been cleared."""
    meta = memory.metadata.get(COMPACTION_META_KEY)
    return bool(isinstance(meta, dict) and meta.get("compacted"))


def apply_compaction(
    memory: StoredMemory,
    *,
    reason: str,
    now: datetime,
    vector_supported: bool = True,
) -> None:
    """Compact a *soft-deleted* memory in place (callers must check status first).

    Clears the retrievable/sensitive payload — content, normalized content, the
    embedding/vector material, and the provenance excerpt — while preserving the
    governance tombstone: id, tenant/user, status (``deleted``), ``deleted_at``,
    ``created_at``, and ``source.kind``. The audit trail lives separately and is
    never touched. Idempotent: re-running clears already-clear fields and rewrites
    the same marker. See ADR-011.
    """
    memory.content = ""
    memory.normalized_content = ""
    memory.embedding = []
    # source.excerpt carries a content excerpt → cleared; kind preserved so
    # provenance (invariant #3) survives compaction.
    memory.source = Source(kind=memory.source.kind)
    memory.metadata = dict(memory.metadata)
    memory.metadata[COMPACTION_META_KEY] = {
        "compacted": True,
        "compacted_at": now.isoformat(),
        "reason": reason,
        "content_compacted": True,
        "vector_purged": vector_supported,
        "purge_status": "purged" if vector_supported else "not_supported",
    }
    memory.updated_at = now


@dataclass
class StoredAudit:
    tenant_id: str
    action: str
    reason: str
    user_id: str | None = None
    memory_id: str | None = None
    trace_id: str | None = None
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=_now)


@dataclass
class StoredSettings:
    tenant_id: str
    user_id: str
    memory_enabled: bool = True
    require_approval_for_sensitive: bool = True
    temporary_chat: bool = False
