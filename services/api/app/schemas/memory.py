"""Pydantic schemas: memory types, decisions, records, and API contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    episodic = "episodic"
    semantic = "semantic"
    procedural = "procedural"
    project = "project"
    knowledge = "knowledge"
    system = "system"
    constraint = "constraint"
    preference = "preference"
    workflow = "workflow"


class Sensitivity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Status(str, Enum):
    active = "active"
    pending = "pending"
    archived = "archived"
    deleted = "deleted"
    rejected = "rejected"
    blocked = "blocked"


class Decision(str, Enum):
    SAVE = "SAVE"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    BLOCK = "BLOCK"
    DROP_LOW_UTILITY = "DROP_LOW_UTILITY"
    MERGE_WITH_EXISTING = "MERGE_WITH_EXISTING"
    UPDATE_EXISTING = "UPDATE_EXISTING"


class Source(BaseModel):
    """Provenance (invariant #3). Always present on a stored memory."""

    kind: str = "chat"  # chat | document | manual | reflection
    excerpt: str = ""
    message_id: str | None = None
    conversation_id: str | None = None


class CandidateMemory(BaseModel):
    content: str
    type: MemoryType = MemoryType.semantic
    confidence: float = Field(0.7, ge=0.0, le=1.0)
    importance: int = Field(5, ge=0, le=10)
    sensitivity: Sensitivity = Sensitivity.low
    source: Source = Field(default_factory=Source)


class CandidateDecision(BaseModel):
    content: str
    decision: Decision
    type: MemoryType
    confidence: float
    importance: int
    sensitivity: Sensitivity
    reason: str
    memory_id: str | None = None  # set when SAVE/UPDATE/MERGE produced a row


class MemoryRecord(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    memory_type: MemoryType
    content: str
    importance: int
    confidence: float
    sensitivity: Sensitivity
    status: Status
    source: Source
    metadata: dict[str, Any] = Field(default_factory=dict)
    weight: float = 1.0
    reinforcement_count: int = 0
    created_at: datetime
    updated_at: datetime


class UsedMemory(BaseModel):
    memory_id: str
    content: str
    memory_type: MemoryType = MemoryType.semantic
    score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    reason: str
    source: Source = Field(default_factory=Source)


# ── API contracts ────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    tenant_id: str
    user_id: str
    message: str
    temporary_chat: bool = False
    conversation_id: str | None = None


class Compression(BaseModel):
    """Token-compression metrics for the composed context (v0.2.1, ADR-007)."""

    enabled: bool = False
    provider: str = "noop"
    original_tokens_estimate: int = 0
    compressed_tokens_estimate: int = 0
    tokens_saved_estimate: int = 0
    compression_ratio: float = 0.0
    fallback: bool = False


class ChatResponse(BaseModel):
    assistant_message: str
    used_memories: list[UsedMemory] = Field(default_factory=list)
    candidate_memories: list[CandidateDecision] = Field(default_factory=list)
    audit_event_ids: list[str] = Field(default_factory=list)
    temporary_chat: bool = False
    # Retrieval mode for explainability: "hybrid" (vector + keyword) or
    # "fallback" (keyword-only after an embedding failure). "none" when memory
    # was bypassed (temporary chat / memory disabled).
    retrieval_mode: str = "none"
    # Optional context compression metrics (present only when compression is
    # configured and there was a context block to compress).
    compression: Compression | None = None
    loop_evidence: dict[str, str] = Field(default_factory=dict)
    trace_id: str


class MemoryPatch(BaseModel):
    tenant_id: str
    user_id: str
    content: str | None = None
    importance: int | None = Field(None, ge=0, le=10)
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    status: Status | None = None  # approve→active, reject→rejected, archive→archived


class DeleteRequest(BaseModel):
    tenant_id: str
    user_id: str


class AuditEvent(BaseModel):
    id: str
    tenant_id: str
    user_id: str | None
    memory_id: str | None
    action: str
    reason: str
    trace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MemoryProvenance(BaseModel):
    """Where a memory came from and why it persists (v0.5 control plane).

    Composed from the stored record plus its audit trail and governance loop
    runs. Never includes embeddings or raw secrets — provenance is metadata.
    """

    memory_id: str
    source: Source
    status: Status
    created_at: datetime
    updated_at: datetime
    reinforcement_count: int
    # Explainability for "why this memory exists / was used": durable signals
    # the ranker reads (no per-request usage log is persisted yet).
    importance: int
    confidence: float
    weight: float
    # The originating + lifecycle audit actions for this memory, newest first.
    audit_trail: list[AuditEvent] = Field(default_factory=list)
    # Governance loop run ids that touched this memory (operational evidence).
    loop_run_ids: list[str] = Field(default_factory=list)
