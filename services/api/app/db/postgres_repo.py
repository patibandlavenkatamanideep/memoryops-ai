"""Postgres + pgvector repository (SQLAlchemy).

Same tenant-scoping and deletion semantics as the in-memory backend. Imported
only when MEMORYOPS_STORAGE=postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import get_settings
from ..loops.metrics import summarize_loop_runs
from ..loops.types import LoopEvent, LoopId, LoopRun, LoopState, LoopStatus
from ..models.sqlalchemy_models import (
    AuditLogORM,
    Base,
    LoopEventORM,
    LoopRunORM,
    MemoryRecordORM,
    SettingsORM,
)
from ..schemas.memory import MemoryType, Sensitivity, Source, Status
from .entities import StoredAudit, StoredMemory, StoredSettings, apply_compaction, is_compacted
from .repository import Repository

_DELETED = "deleted"
_ACTIVE = "active"


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _to_stored(row: MemoryRecordORM) -> StoredMemory:
    return StoredMemory(
        id=row.id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        memory_type=MemoryType(row.memory_type),
        content=row.content,
        normalized_content=row.normalized_content or "",
        embedding=list(row.embedding) if row.embedding is not None else [],
        importance=row.importance,
        confidence=row.confidence,
        sensitivity=Sensitivity(row.sensitivity),
        status=Status(row.status),
        source=Source(**(row.source or {})),
        metadata=row.extra_metadata or {},
        weight=row.weight,
        reinforcement_count=row.reinforcement_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
        deleted_at=row.deleted_at,
    )


def _parse_dt(value) -> str:
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _loop_run_from_row(row: LoopRunORM) -> LoopRun:
    return LoopRun(
        id=row.id,
        loop_id=LoopId(row.loop_id),
        trace_id=row.trace_id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        status=LoopStatus(row.status),
        started_at=_parse_dt(row.started_at),
        ended_at=_parse_dt(row.ended_at) if row.ended_at else None,
        metadata=row.extra_metadata or {},
    )


def _loop_event_from_row(row: LoopEventORM) -> LoopEvent:
    return LoopEvent(
        id=row.id,
        loop_run_id=row.loop_run_id,
        loop_id=LoopId(row.loop_id),
        trace_id=row.trace_id,
        state_from=LoopState(row.state_from) if row.state_from else None,
        state_to=LoopState(row.state_to),
        event_type=row.event_type,
        reason=row.reason,
        evidence=row.evidence or {},
        audit_event_id=row.audit_event_id,
        created_at=_parse_dt(row.created_at),
    )


class PostgresRepository(Repository):
    def __init__(self) -> None:
        settings = get_settings()
        self._engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
        self._Session: sessionmaker[Session] = sessionmaker(self._engine, expire_on_commit=False)
        # Migrations own the canonical schema; create_all is a dev convenience.
        Base.metadata.create_all(self._engine)

    @contextmanager
    def _scoped(self, tenant_id: str, user_id: str = "") -> Iterator[Session]:
        """Open a session with the per-request RLS context set.

        Sets ``app.tenant_id`` (and ``app.user_id``) as transaction-local GUCs so
        the Row-Level Security policies in migration 004 enforce tenant isolation
        at the database, not just in application code (defense in depth).
        """
        with self._Session() as s:
            s.execute(
                text("select set_config('app.tenant_id', :t, true)"), {"t": tenant_id or ""}
            )
            s.execute(
                text("select set_config('app.user_id', :u, true)"), {"u": user_id or ""}
            )
            yield s

    # ── memory ───────────────────────────────────────────────────────────────
    def create_memory(self, memory: StoredMemory) -> StoredMemory:
        if not memory.source:
            raise ValueError("memory.source (provenance) is required")
        with self._scoped(memory.tenant_id, memory.user_id) as s:
            row = MemoryRecordORM(
                id=memory.id,
                tenant_id=memory.tenant_id,
                user_id=memory.user_id,
                memory_type=memory.memory_type.value,
                content=memory.content,
                normalized_content=memory.normalized_content or _norm(memory.content),
                embedding=memory.embedding or None,
                importance=memory.importance,
                confidence=memory.confidence,
                sensitivity=memory.sensitivity.value,
                status=memory.status.value,
                source=memory.source.model_dump(),
                extra_metadata=memory.metadata,
                weight=memory.weight,
                reinforcement_count=memory.reinforcement_count,
            )
            s.add(row)
            s.commit()
            return _to_stored(row)

    def get_memory(self, tenant_id: str, user_id: str, memory_id: str) -> StoredMemory | None:
        with self._scoped(tenant_id, user_id) as s:
            row = s.get(MemoryRecordORM, memory_id)
            if row and row.tenant_id == tenant_id and row.user_id == user_id:
                return _to_stored(row)
            return None

    def list_memories(
        self,
        tenant_id: str,
        user_id: str,
        *,
        status: str | None = None,
        memory_type: str | None = None,
        include_deleted: bool = False,
    ) -> list[StoredMemory]:
        with self._scoped(tenant_id, user_id) as s:
            stmt = select(MemoryRecordORM).where(
                MemoryRecordORM.tenant_id == tenant_id,
                MemoryRecordORM.user_id == user_id,
            )
            if not include_deleted:
                stmt = stmt.where(MemoryRecordORM.status != _DELETED)
            if status:
                stmt = stmt.where(MemoryRecordORM.status == status)
            if memory_type:
                stmt = stmt.where(MemoryRecordORM.memory_type == memory_type)
            stmt = stmt.order_by(MemoryRecordORM.created_at.desc())
            return [_to_stored(r) for r in s.scalars(stmt)]

    def update_memory(self, memory: StoredMemory) -> StoredMemory:
        with self._scoped(memory.tenant_id, memory.user_id) as s:
            row = s.get(MemoryRecordORM, memory.id)
            if not row:
                raise ValueError("memory not found")
            row.content = memory.content
            row.importance = memory.importance
            row.confidence = memory.confidence
            row.sensitivity = memory.sensitivity.value
            row.status = memory.status.value
            row.weight = memory.weight
            row.reinforcement_count = memory.reinforcement_count
            row.updated_at = datetime.now(UTC)
            s.commit()
            return _to_stored(row)

    def soft_delete(self, tenant_id: str, user_id: str, memory_id: str) -> StoredMemory | None:
        with self._scoped(tenant_id, user_id) as s:
            row = s.get(MemoryRecordORM, memory_id)
            if not row or row.tenant_id != tenant_id or row.user_id != user_id:
                return None
            row.status = _DELETED
            now = datetime.now(UTC)
            row.deleted_at = now
            row.updated_at = now
            s.commit()
            return _to_stored(row)

    def list_deleted_for_compaction(
        self, tenant_id: str, user_id: str, *, include_compacted: bool = False
    ) -> list[StoredMemory]:
        with self._scoped(tenant_id, user_id) as s:
            stmt = (
                select(MemoryRecordORM)
                .where(
                    MemoryRecordORM.tenant_id == tenant_id,
                    MemoryRecordORM.user_id == user_id,
                    MemoryRecordORM.status == _DELETED,
                )
                .order_by(MemoryRecordORM.deleted_at.desc())
            )
            rows = [_to_stored(r) for r in s.scalars(stmt)]
        if not include_compacted:
            rows = [m for m in rows if not is_compacted(m)]
        return rows

    def compact_deleted_memory(
        self,
        tenant_id: str,
        user_id: str,
        memory_id: str,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> StoredMemory | None:
        with self._scoped(tenant_id, user_id) as s:
            row = s.get(MemoryRecordORM, memory_id)
            if (
                not row
                or row.tenant_id != tenant_id
                or row.user_id != user_id
                or row.status != _DELETED
            ):
                return None
            stored = _to_stored(row)
            apply_compaction(stored, reason=reason, now=now or datetime.now(UTC))
            # Clear retrievable content + vector material; tombstone columns
            # (id, tenant_id, user_id, status, deleted_at, created_at) untouched.
            row.content = stored.content
            row.normalized_content = stored.normalized_content
            row.embedding = None  # vector column → NULL (material removed)
            row.source = stored.source.model_dump()
            row.extra_metadata = stored.metadata
            row.updated_at = stored.updated_at
            s.commit()
            return _to_stored(row)

    def find_similar_active(
        self, tenant_id: str, user_id: str, content: str
    ) -> StoredMemory | None:
        with self._scoped(tenant_id, user_id) as s:
            stmt = select(MemoryRecordORM).where(
                MemoryRecordORM.tenant_id == tenant_id,
                MemoryRecordORM.user_id == user_id,
                MemoryRecordORM.status == _ACTIVE,
                MemoryRecordORM.normalized_content == _norm(content),
            )
            row = s.scalars(stmt).first()
            return _to_stored(row) if row else None

    def retrieve_active(self, tenant_id: str, user_id: str) -> list[StoredMemory]:
        return self.list_memories(tenant_id, user_id, status=_ACTIVE)

    def search_candidates(
        self,
        tenant_id: str,
        user_id: str,
        query_embedding: list[float],
        *,
        limit: int = 50,
    ) -> list[tuple[StoredMemory, float]]:
        with self._scoped(tenant_id, user_id) as s:
            base = select(MemoryRecordORM).where(
                MemoryRecordORM.tenant_id == tenant_id,
                MemoryRecordORM.user_id == user_id,
                MemoryRecordORM.status == _ACTIVE,
                MemoryRecordORM.deleted_at.is_(None),
            )
            if not query_embedding:
                # Embedding failure → return active rows; caller degrades to keyword.
                rows = s.scalars(base.limit(limit))
                return [(_to_stored(r), 0.0) for r in rows]
            # Real pgvector cosine search: 1 - cosine_distance = cosine similarity.
            distance = MemoryRecordORM.embedding.cosine_distance(query_embedding)
            stmt = (
                base.where(MemoryRecordORM.embedding.is_not(None))
                .add_columns((1 - distance).label("similarity"))
                .order_by(distance)
                .limit(limit)
            )
            out: list[tuple[StoredMemory, float]] = []
            for row, similarity in s.execute(stmt):
                out.append((_to_stored(row), float(similarity)))
            return out

    # ── audit ────────────────────────────────────────────────────────────────
    def add_audit(self, event: StoredAudit) -> StoredAudit:
        with self._scoped(event.tenant_id, event.user_id or "") as s:
            row = AuditLogORM(
                id=event.id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                memory_id=event.memory_id,
                action=event.action,
                reason=event.reason,
                trace_id=event.trace_id,
                extra_metadata=event.metadata,
            )
            s.add(row)
            s.commit()
            return event

    def list_audit(
        self,
        tenant_id: str,
        user_id: str | None = None,
        *,
        memory_id: str | None = None,
        limit: int = 200,
    ) -> list[StoredAudit]:
        with self._scoped(tenant_id, user_id or "") as s:
            stmt = select(AuditLogORM).where(AuditLogORM.tenant_id == tenant_id)
            if user_id:
                stmt = stmt.where(AuditLogORM.user_id == user_id)
            if memory_id:
                stmt = stmt.where(AuditLogORM.memory_id == memory_id)
            stmt = stmt.order_by(AuditLogORM.created_at.desc()).limit(limit)
            return [
                StoredAudit(
                    id=r.id,
                    tenant_id=r.tenant_id,
                    user_id=r.user_id,
                    memory_id=r.memory_id,
                    action=r.action,
                    reason=r.reason,
                    trace_id=r.trace_id,
                    metadata=r.extra_metadata or {},
                    created_at=r.created_at,
                )
                for r in s.scalars(stmt)
            ]

    # ── settings ─────────────────────────────────────────────────────────────
    def get_settings(self, tenant_id: str, user_id: str) -> StoredSettings:
        with self._scoped(tenant_id, user_id) as s:
            stmt = select(SettingsORM).where(
                SettingsORM.tenant_id == tenant_id, SettingsORM.user_id == user_id
            )
            row = s.scalars(stmt).first()
            if not row:
                return StoredSettings(tenant_id=tenant_id, user_id=user_id)
            return StoredSettings(
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                memory_enabled=row.memory_enabled,
                require_approval_for_sensitive=row.require_approval_for_sensitive,
                temporary_chat=row.temporary_chat,
            )

    def upsert_settings(self, settings: StoredSettings) -> StoredSettings:
        with self._scoped(settings.tenant_id, settings.user_id) as s:
            stmt = select(SettingsORM).where(
                SettingsORM.tenant_id == settings.tenant_id,
                SettingsORM.user_id == settings.user_id,
            )
            row = s.scalars(stmt).first()
            if not row:
                row = SettingsORM(tenant_id=settings.tenant_id, user_id=settings.user_id)
                s.add(row)
            row.memory_enabled = settings.memory_enabled
            row.require_approval_for_sensitive = settings.require_approval_for_sensitive
            row.temporary_chat = settings.temporary_chat
            row.updated_at = datetime.now(UTC)
            s.commit()
            return settings

    # ── metrics ──────────────────────────────────────────────────────────────
    def metrics(self, tenant_id: str) -> dict:
        with self._scoped(tenant_id) as s:
            mems = list(
                s.scalars(
                    select(MemoryRecordORM).where(MemoryRecordORM.tenant_id == tenant_id)
                )
            )
            audit = list(
                s.scalars(select(AuditLogORM).where(AuditLogORM.tenant_id == tenant_id))
            )
        by_status: dict[str, int] = {}
        for m in mems:
            by_status[m.status] = by_status.get(m.status, 0) + 1
        by_action: dict[str, int] = {}
        for e in audit:
            by_action[e.action] = by_action.get(e.action, 0) + 1
        return {
            "total_memories": len(mems),
            "by_status": by_status,
            "audit_events": len(audit),
            "by_action": by_action,
            "loops": summarize_loop_runs(self.list_loop_runs(tenant_id=tenant_id)),
        }

    # ── loops ────────────────────────────────────────────────────────────────
    def add_loop_run(self, run: LoopRun) -> LoopRun:
        with self._scoped(run.tenant_id or "", run.user_id or "") as s:
            row = LoopRunORM(
                id=run.id,
                loop_id=run.loop_id.value,
                trace_id=run.trace_id,
                tenant_id=run.tenant_id,
                user_id=run.user_id,
                status=run.status.value,
                extra_metadata=run.metadata,
            )
            s.add(row)
            s.commit()
            return run

    def update_loop_run(self, run: LoopRun) -> LoopRun:
        with self._scoped(run.tenant_id or "", run.user_id or "") as s:
            row = s.get(LoopRunORM, run.id)
            if not row:
                raise ValueError("loop run not found")
            row.status = run.status.value
            row.ended_at = datetime.fromisoformat(run.ended_at) if run.ended_at else None
            row.extra_metadata = run.metadata
            s.commit()
            return run

    def list_loop_runs(
        self,
        *,
        loop_id: str | None = None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[LoopRun]:
        with self._scoped(tenant_id or "", user_id or "") as s:
            stmt = select(LoopRunORM)
            if loop_id:
                stmt = stmt.where(LoopRunORM.loop_id == loop_id)
            if trace_id:
                stmt = stmt.where(LoopRunORM.trace_id == trace_id)
            if tenant_id:
                stmt = stmt.where(LoopRunORM.tenant_id == tenant_id)
            if user_id:
                stmt = stmt.where(LoopRunORM.user_id == user_id)
            if status:
                stmt = stmt.where(LoopRunORM.status == status)
            stmt = stmt.order_by(LoopRunORM.started_at.desc()).limit(limit)
            return [_loop_run_from_row(r) for r in s.scalars(stmt)]

    def add_loop_event(self, event: LoopEvent) -> LoopEvent:
        with self._scoped("", "") as s:
            row = LoopEventORM(
                id=event.id,
                loop_run_id=event.loop_run_id,
                loop_id=event.loop_id.value,
                trace_id=event.trace_id,
                state_from=event.state_from.value if event.state_from else None,
                state_to=event.state_to.value,
                event_type=event.event_type,
                reason=event.reason,
                evidence=event.evidence,
                audit_event_id=event.audit_event_id,
            )
            s.add(row)
            s.commit()
            return event

    def list_loop_events(
        self,
        *,
        loop_run_id: str | None = None,
        loop_id: str | None = None,
        trace_id: str | None = None,
        event_type: str | None = None,
        limit: int = 500,
    ) -> list[LoopEvent]:
        with self._scoped("", "") as s:
            stmt = select(LoopEventORM)
            if loop_run_id:
                stmt = stmt.where(LoopEventORM.loop_run_id == loop_run_id)
            if loop_id:
                stmt = stmt.where(LoopEventORM.loop_id == loop_id)
            if trace_id:
                stmt = stmt.where(LoopEventORM.trace_id == trace_id)
            if event_type:
                stmt = stmt.where(LoopEventORM.event_type == event_type)
            stmt = stmt.order_by(LoopEventORM.created_at.desc()).limit(limit)
            return [_loop_event_from_row(r) for r in s.scalars(stmt)]
