"""Postgres + pgvector repository (SQLAlchemy).

Same tenant-scoping and deletion semantics as the in-memory backend. Imported
only when MEMORYOPS_STORAGE=postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import get_settings
from ..loops.metrics import summarize_loop_runs
from ..loops.types import LoopEvent, LoopId, LoopRun, LoopState, LoopStatus
from ..models.sqlalchemy_models import (
    AuditLogORM,
    LoopEventORM,
    LoopRunORM,
    MemoryRecordORM,
    SettingsORM,
    WorkerLeaseORM,
    WorkerRunORM,
)
from ..schemas.memory import MemoryType, Sensitivity, Source, Status
from .entities import (
    StoredAudit,
    StoredMemory,
    StoredSettings,
    WorkerLease,
    WorkerRunRecord,
    apply_compaction,
    is_compacted,
)
from .repository import Repository

_DELETED = "deleted"
_ACTIVE = "active"
_CURRENT_SCHEMA_VERSION = "010_transactional_audit_chain"


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
        self._active_session: ContextVar[Session | None] = ContextVar(
            "memoryops_pg_session", default=None
        )
        self._active_tenant: ContextVar[str] = ContextVar("memoryops_pg_tenant", default="")
        self._active_user: ContextVar[str] = ContextVar("memoryops_pg_user", default="")
        self._assert_current_schema()

    def _assert_current_schema(self) -> None:
        """Fail clearly when the database has not been migrated."""
        with self._engine.connect() as conn:
            has_marker = conn.execute(
                text(
                    """
                    select exists (
                      select 1
                      from information_schema.tables
                      where table_schema = 'public'
                        and table_name = 'memoryops_schema_migrations'
                    )
                    """
                )
            ).scalar_one()
            if not has_marker:
                raise RuntimeError(
                    "Postgres schema is not migrated: missing "
                    "memoryops_schema_migrations. Apply infra/db/migrations before startup."
                )
            applied = conn.execute(
                text(
                    "select 1 from memoryops_schema_migrations "
                    "where version = :version"
                ),
                {"version": _CURRENT_SCHEMA_VERSION},
            ).scalar()
            if not applied:
                raise RuntimeError(
                    "Postgres schema is outdated: missing migration "
                    f"{_CURRENT_SCHEMA_VERSION}."
                )

    @contextmanager
    def transaction(self, tenant_id: str, user_id: str = "") -> Iterator[None]:
        active = self._active_session.get()
        if active is not None:
            self._validate_active_scope(tenant_id, user_id)
            yield
            return
        with self._Session() as s:
            self._set_scope(s, tenant_id, user_id)
            session_token = self._active_session.set(s)
            tenant_token = self._active_tenant.set(tenant_id or "")
            user_token = self._active_user.set(user_id or "")
            try:
                yield
                s.commit()
            except Exception:
                s.rollback()
                raise
            finally:
                self._active_session.reset(session_token)
                self._active_tenant.reset(tenant_token)
                self._active_user.reset(user_token)

    def _set_scope(self, s: Session, tenant_id: str, user_id: str = "") -> None:
        s.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": tenant_id or ""})
        s.execute(text("select set_config('app.user_id', :u, true)"), {"u": user_id or ""})

    def _validate_active_scope(self, tenant_id: str, user_id: str = "") -> None:
        active_tenant = self._active_tenant.get()
        active_user = self._active_user.get()
        if tenant_id and active_tenant and tenant_id != active_tenant:
            raise ValueError("cross-tenant repository call inside active transaction")
        if user_id and active_user and user_id != active_user:
            raise ValueError("cross-user repository call inside active transaction")

    def _commit(self, s: Session) -> None:
        if self._active_session.get() is None:
            s.commit()

    @contextmanager
    def _scoped(self, tenant_id: str, user_id: str = "") -> Iterator[Session]:
        """Open a session with the per-request RLS context set.

        Sets ``app.tenant_id`` (and ``app.user_id``) as transaction-local GUCs so
        the Row-Level Security policies in migration 004 enforce tenant isolation
        at the database, not just in application code (defense in depth).
        """
        active = self._active_session.get()
        if active is not None:
            self._validate_active_scope(tenant_id, user_id)
            yield active
            return
        with self._Session() as s:
            self._set_scope(s, tenant_id, user_id)
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
            self._commit(s)
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
            # Persist metadata so lifecycle markers (decay/archive) and v0.10
            # governance state (legal hold, consent, retention) survive updates.
            row.extra_metadata = memory.metadata
            row.weight = memory.weight
            row.reinforcement_count = memory.reinforcement_count
            row.updated_at = datetime.now(UTC)
            self._commit(s)
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
            self._commit(s)
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
            self._commit(s)
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
            from ..evidence.hashchain import GENESIS, compute_entry_hash

            prev_hash = s.scalars(
                select(AuditLogORM.entry_hash)
                .where(
                    AuditLogORM.tenant_id == event.tenant_id,
                    AuditLogORM.entry_hash != "",
                )
                .order_by(AuditLogORM.created_at.desc())
                .limit(1)
            ).first() or GENESIS
            event.prev_hash = prev_hash
            event.entry_hash = compute_entry_hash(event, prev_hash)
            row = AuditLogORM(
                id=event.id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                memory_id=event.memory_id,
                action=event.action,
                reason=event.reason,
                trace_id=event.trace_id,
                extra_metadata=event.metadata,
                created_at=event.created_at,
                prev_hash=event.prev_hash,
                entry_hash=event.entry_hash,
            )
            s.add(row)
            self._commit(s)
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
                    prev_hash=r.prev_hash or "",
                    entry_hash=r.entry_hash or "",
                )
                for r in s.scalars(stmt)
            ]

    # ── worker runtime (v0.8) ──────────────────────────────────────────────────
    def try_acquire_lease(
        self, key: str, owner: str, *, now: datetime, expires_at: datetime
    ) -> bool:
        # Atomic acquire: insert, or take over only if the prior lease expired or
        # is ours. RETURNING owner tells us whether we now hold it.
        sql = text(
            """
            INSERT INTO worker_leases (key, owner, acquired_at, expires_at)
            VALUES (:key, :owner, :now, :exp)
            ON CONFLICT (key) DO UPDATE
              SET owner = excluded.owner,
                  acquired_at = excluded.acquired_at,
                  expires_at = excluded.expires_at
              WHERE worker_leases.expires_at <= :now OR worker_leases.owner = :owner
            RETURNING owner
            """
        )
        with self._Session() as s:
            row = s.execute(
                sql, {"key": key, "owner": owner, "now": now, "exp": expires_at}
            ).first()
            self._commit(s)
            return bool(row and row[0] == owner)

    def renew_lease(self, key: str, owner: str, *, expires_at: datetime) -> bool:
        with self._Session() as s:
            row = s.get(WorkerLeaseORM, key)
            if not row or row.owner != owner:
                return False
            row.expires_at = expires_at
            self._commit(s)
            return True

    def release_lease(self, key: str, owner: str) -> None:
        with self._Session() as s:
            row = s.get(WorkerLeaseORM, key)
            if row and row.owner == owner:
                s.delete(row)
                self._commit(s)

    def get_lease(self, key: str) -> WorkerLease | None:
        with self._Session() as s:
            row = s.get(WorkerLeaseORM, key)
            if not row:
                return None
            return WorkerLease(
                key=row.key,
                owner=row.owner,
                acquired_at=row.acquired_at,
                expires_at=row.expires_at,
            )

    def add_worker_run(self, record: WorkerRunRecord) -> WorkerRunRecord:
        with self._scoped(record.tenant_id, record.user_id) as s:
            s.add(
                WorkerRunORM(
                    id=record.id,
                    tenant_id=record.tenant_id,
                    user_id=record.user_id,
                    status=record.status,
                    jobs=list(record.jobs),
                    attempts=record.attempts,
                    scanned_count=record.scanned_count,
                    changed_count=record.changed_count,
                    skipped_count=record.skipped_count,
                    error_count=record.error_count,
                    owner=record.owner,
                    trace_id=record.trace_id,
                    error=record.error,
                    extra_metadata=record.details,
                    started_at=record.started_at,
                    completed_at=record.completed_at,
                )
            )
            self._commit(s)
            return record

    def list_worker_runs(
        self,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[WorkerRunRecord]:
        if not tenant_id:
            raise ValueError("tenant_id is required when listing worker run evidence")
        with self._scoped(tenant_id, user_id or "") as s:
            stmt = select(WorkerRunORM).where(WorkerRunORM.tenant_id == tenant_id)
            if user_id:
                stmt = stmt.where(WorkerRunORM.user_id == user_id)
            if status:
                stmt = stmt.where(WorkerRunORM.status == status)
            stmt = stmt.order_by(WorkerRunORM.started_at.desc()).limit(limit)
            return [
                WorkerRunRecord(
                    id=r.id,
                    tenant_id=r.tenant_id,
                    user_id=r.user_id,
                    status=r.status,
                    jobs=list(r.jobs or []),
                    attempts=r.attempts,
                    scanned_count=r.scanned_count,
                    changed_count=r.changed_count,
                    skipped_count=r.skipped_count,
                    error_count=r.error_count,
                    owner=r.owner,
                    trace_id=r.trace_id,
                    error=r.error,
                    details=r.extra_metadata or {},
                    started_at=r.started_at,
                    completed_at=r.completed_at,
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
            self._commit(s)
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
        if not run.tenant_id:
            raise ValueError("tenant_id is required for loop run evidence")
        with self._scoped(run.tenant_id, run.user_id or "") as s:
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
            self._commit(s)
            return run

    def update_loop_run(self, run: LoopRun) -> LoopRun:
        if not run.tenant_id:
            raise ValueError("tenant_id is required for loop run evidence")
        with self._scoped(run.tenant_id, run.user_id or "") as s:
            row = s.get(LoopRunORM, run.id)
            if not row:
                raise ValueError("loop run not found")
            row.status = run.status.value
            row.ended_at = datetime.fromisoformat(run.ended_at) if run.ended_at else None
            row.extra_metadata = run.metadata
            self._commit(s)
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
        if not tenant_id:
            raise ValueError("tenant_id is required when listing loop run evidence")
        with self._scoped(tenant_id, user_id or "") as s:
            stmt = select(LoopRunORM).where(LoopRunORM.tenant_id == tenant_id)
            if loop_id:
                stmt = stmt.where(LoopRunORM.loop_id == loop_id)
            if trace_id:
                stmt = stmt.where(LoopRunORM.trace_id == trace_id)
            if user_id:
                stmt = stmt.where(LoopRunORM.user_id == user_id)
            if status:
                stmt = stmt.where(LoopRunORM.status == status)
            stmt = stmt.order_by(LoopRunORM.started_at.desc()).limit(limit)
            return [_loop_run_from_row(r) for r in s.scalars(stmt)]

    def add_loop_event(
        self,
        event: LoopEvent,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> LoopEvent:
        if not tenant_id:
            raise ValueError("tenant_id is required for loop event evidence")
        with self._scoped(tenant_id, user_id or "") as s:
            parent = s.get(LoopRunORM, event.loop_run_id)
            if not parent or parent.tenant_id != tenant_id:
                raise ValueError("loop event parent run not found in tenant scope")
            if user_id and parent.user_id != user_id:
                raise ValueError("loop event parent run not found in user scope")
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
            self._commit(s)
            return event

    def list_loop_events(
        self,
        *,
        loop_run_id: str | None = None,
        loop_id: str | None = None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        limit: int = 500,
    ) -> list[LoopEvent]:
        if not tenant_id:
            raise ValueError("tenant_id is required when listing loop event evidence")
        with self._scoped(tenant_id, user_id or "") as s:
            stmt = select(LoopEventORM).join(
                LoopRunORM, LoopRunORM.id == LoopEventORM.loop_run_id
            ).where(LoopRunORM.tenant_id == tenant_id)
            if loop_run_id:
                stmt = stmt.where(LoopEventORM.loop_run_id == loop_run_id)
            if loop_id:
                stmt = stmt.where(LoopEventORM.loop_id == loop_id)
            if trace_id:
                stmt = stmt.where(LoopEventORM.trace_id == trace_id)
            if user_id:
                stmt = stmt.where(LoopRunORM.user_id == user_id)
            if event_type:
                stmt = stmt.where(LoopEventORM.event_type == event_type)
            stmt = stmt.order_by(LoopEventORM.created_at.desc()).limit(limit)
            return [_loop_event_from_row(r) for r in s.scalars(stmt)]
