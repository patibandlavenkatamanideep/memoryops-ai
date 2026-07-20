"""Pydantic schemas: memory types, decisions, records, and API contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

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


# ── Memory Usage Trace (v1.3, ADR-017) ────────────────────────────────────────
class MemoryTraceEntry(BaseModel):
    """One retrieved memory's admission verdict + provenance for a chat turn.

    Content is surfaced as a short preview only; the caller already owns the
    tenant scope (same trust boundary as ``used_memories``).
    """

    memory_id: str
    memory_type: MemoryType
    content_preview: str
    source: Source
    stored_at: datetime
    status: Status
    sensitivity: Sensitivity
    consent_status: str
    retention_status: str  # active | expired | exempt | none
    admission_decision: str  # ALLOW | BLOCK_*
    admission_reason: str
    retrieval_score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)


class MemoryUsageTrace(BaseModel):
    """The full memory trail behind one answer (invariant #8, ADR-017).

    Explains *why each memory was (or was not) allowed into context* — not just
    that it was relevant. ``memories_used`` shaped the answer; ``memories_blocked``
    were retrieved but denied admission with a reason.
    """

    response_id: str
    memories_used: list[MemoryTraceEntry] = Field(default_factory=list)
    memories_blocked: list[MemoryTraceEntry] = Field(default_factory=list)
    admission_counts: dict[str, int] = Field(default_factory=dict)


# ── API contracts ────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    # max_length caps bound abuse / oversized payloads (P2.4). tenant_id/user_id
    # require min_length=1: an empty scope is invalid input, so it is rejected at the
    # boundary (422) instead of flowing through the pipeline with no owner. Odd-but-
    # non-empty ids (wildcards, injection-looking strings, whitespace) are still
    # allowed and defused by parameterized scoping — that is what the isolation evals
    # probe. (Empty scope was previously allowed on purpose; that let an empty-tenant
    # probe crash the Postgres loop-evidence path — invariant #4 — so it is now
    # rejected up front, which is also stronger isolation.)
    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    message: str = Field(max_length=8000)
    temporary_chat: bool = False
    conversation_id: str | None = None
    # Audience/clearance for this session (v1.9, ADR-023). The Recall Gate admits a
    # memory into context only if its sensitivity is permitted for this audience:
    #   private (default) → low + medium + high   (full clearance; no behavior change)
    #   team              → low + medium
    #   public            → low only
    audience: Literal["private", "team", "public"] = "private"


class OutputGateResult(BaseModel):
    """Post-generation disclosure control (v1.9, ADR-023).

    The Output Gate inspects the final answer *after* generation and redacts (or
    refuses) content that would disclose memory the Recall/Admission gates blocked —
    catching leakage the pre-composition gates cannot see.
    """

    action: str  # allow | redacted | refused
    disclosures: int = 0  # number of protected memories whose content was caught
    escalated: bool = False


class Compression(BaseModel):
    """Token-compression metrics for the composed context (v0.2.1, ADR-007)."""

    enabled: bool = False
    provider: str = "noop"
    original_tokens_estimate: int = 0
    compressed_tokens_estimate: int = 0
    tokens_saved_estimate: int = 0
    compression_ratio: float = 0.0
    fallback: bool = False


class Economics(BaseModel):
    """Advisory per-request token + cost estimate (v1.2, ADR-016).

    Costs are list-price *estimates* for instrumentation, never billing.
    `priced=false` means the active model is unpriced (e.g. the stub provider) and
    costs are 0 even though token counts are real.
    """

    embedding_model: str = ""
    llm_model: str = ""
    embedding_tokens: int = 0
    context_tokens: int = 0
    compressed_tokens: int = 0
    tokens_saved: int = 0
    llm_input_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cost_saved_usd: float = 0.0
    priced: bool = False


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
    # Optional advisory token + cost estimate for this request (v1.2, ADR-016).
    economics: Economics | None = None
    # Optional memory usage trace: the permissioned, explainable memory trail
    # behind this answer (v1.3, ADR-017). Present when the trace is enabled.
    trace: MemoryUsageTrace | None = None
    # Optional Output Gate result (v1.9, ADR-023). Present only when the gate acted
    # (redacted / refused) — i.e. it caught a would-be disclosure post-generation.
    output_gate: OutputGateResult | None = None
    loop_evidence: dict[str, str] = Field(default_factory=dict)
    trace_id: str


class MemoryPatch(BaseModel):
    tenant_id: str = Field(max_length=200)
    user_id: str = Field(max_length=200)
    content: str | None = Field(default=None, max_length=8000)
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
