"""SQLAlchemy ORM models for the Postgres backend.

Imported lazily (only when MEMORYOPS_STORAGE=postgres) so the in-memory backend
and tests don't require sqlalchemy/pgvector to be installed. Mirrors
infra/db/migrations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class MemoryRecordORM(Base):
    __tablename__ = "memory_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    memory_type: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    normalized_content: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=5)
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    sensitivity: Mapped[str] = mapped_column(String, default="low")
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    source: Mapped[dict] = mapped_column(JSON)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    reinforcement_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLogORM(Base):
    __tablename__ = "memory_audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    memory_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String, default="")
    entry_hash: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditChainHeadORM(Base):
    """One row per tenant holding the current audit hash-chain head (migration
    011). The append path locks this row with SELECT ... FOR UPDATE so concurrent
    audited mutations serialize onto one continuous chain instead of forking."""

    __tablename__ = "audit_chain_heads"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    head_hash: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LoopRunORM(Base):
    __tablename__ = "loop_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    loop_id: Mapped[str] = mapped_column(String, index=True)
    trace_id: Mapped[str] = mapped_column(String, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class LoopEventORM(Base):
    __tablename__ = "loop_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    loop_run_id: Mapped[str] = mapped_column(String, index=True)
    loop_id: Mapped[str] = mapped_column(String, index=True)
    trace_id: Mapped[str] = mapped_column(String, index=True)
    state_from: Mapped[str | None] = mapped_column(String, nullable=True)
    state_to: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String, index=True)
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    audit_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WorkerLeaseORM(Base):
    __tablename__ = "worker_leases"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[str] = mapped_column(String)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class WorkerRunORM(Base):
    __tablename__ = "worker_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    jobs: Mapped[dict] = mapped_column(JSON, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    scanned_count: Mapped[int] = mapped_column(Integer, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    owner: Mapped[str] = mapped_column(String, default="")
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SettingsORM(Base):
    __tablename__ = "memory_settings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    require_approval_for_sensitive: Mapped[bool] = mapped_column(Boolean, default=True)
    temporary_chat: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
