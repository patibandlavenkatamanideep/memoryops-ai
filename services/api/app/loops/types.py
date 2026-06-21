"""Typed loop engineering contracts (v0.2.2).

Loop traces are operational evidence. They intentionally carry structured,
sanitized metadata instead of raw prompts, secrets, or full memory contents.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class LoopId(StrEnum):
    MEMORY_WRITE = "memory.write"
    MEMORY_READ = "memory.read"
    MEMORY_GOVERNANCE = "memory.governance"
    MEMORY_EVALUATION = "memory.evaluation"
    RELEASE_GATE = "release.gate"
    LEARNING_CONTINUOUS = "learning.continuous"


class LoopState(StrEnum):
    OBSERVED = "observed"
    CLASSIFIED = "classified"
    POLICY_CHECKED = "policy_checked"
    EXECUTED = "executed"
    VERIFIED = "verified"
    AUDITED = "audited"
    FEEDBACK_CAPTURED = "feedback_captured"
    LEARNED = "learned"
    SAFE_DEGRADED = "safe_degraded"
    FAILED = "failed"
    COMPLETED = "completed"


class LoopStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    SAFE_DEGRADED = "safe_degraded"
    FAILED = "failed"


class LoopDefinition(BaseModel):
    id: LoopId
    name: str
    purpose: str
    trigger: str
    input_contract: str
    output_contract: str
    states: list[LoopState]
    policy_gates: list[str]
    audit_events: list[str]
    failure_modes: list[str]
    fallback_behavior: list[str]
    evidence_required: list[str]


class LoopRun(BaseModel):
    id: str
    loop_id: LoopId
    trace_id: str
    tenant_id: str | None = None
    user_id: str | None = None
    status: LoopStatus
    started_at: str
    ended_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LoopEvent(BaseModel):
    id: str
    loop_run_id: str
    loop_id: LoopId
    trace_id: str
    state_from: LoopState | None = None
    state_to: LoopState
    event_type: str
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    audit_event_id: str | None = None
    created_at: str


class LoopTrace(BaseModel):
    trace_id: str
    runs: list[LoopRun] = Field(default_factory=list)
    events: list[LoopEvent] = Field(default_factory=list)
