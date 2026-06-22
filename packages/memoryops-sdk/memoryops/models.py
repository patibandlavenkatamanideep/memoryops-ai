"""Lightweight typed models for MemoryOps API responses.

These are thin, forgiving dataclasses: each keeps the full ``raw`` payload so new
server fields are never lost, while surfacing the common fields with types. Use
``.raw`` whenever you need something not modeled here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UsedMemory:
    memory_id: str
    content: str
    score: float
    memory_type: str = "semantic"
    reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> UsedMemory:
        return cls(
            memory_id=d.get("memory_id", ""),
            content=d.get("content", ""),
            score=d.get("score", 0.0),
            memory_type=d.get("memory_type", "semantic"),
            reason=d.get("reason", ""),
            raw=d,
        )


@dataclass
class CandidateDecision:
    content: str
    decision: str
    reason: str = ""
    memory_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> CandidateDecision:
        return cls(
            content=d.get("content", ""),
            decision=d.get("decision", ""),
            reason=d.get("reason", ""),
            memory_id=d.get("memory_id"),
            raw=d,
        )


@dataclass
class ChatResult:
    assistant_message: str
    used_memories: list[UsedMemory]
    candidate_memories: list[CandidateDecision]
    retrieval_mode: str
    trace_id: str
    temporary_chat: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> ChatResult:
        return cls(
            assistant_message=d.get("assistant_message", ""),
            used_memories=[UsedMemory.from_dict(m) for m in d.get("used_memories", [])],
            candidate_memories=[
                CandidateDecision.from_dict(c) for c in d.get("candidate_memories", [])
            ],
            retrieval_mode=d.get("retrieval_mode", "none"),
            trace_id=d.get("trace_id", ""),
            temporary_chat=d.get("temporary_chat", False),
            raw=d,
        )


@dataclass
class Memory:
    id: str
    content: str
    memory_type: str
    status: str
    importance: int
    confidence: float
    sensitivity: str
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> Memory:
        return cls(
            id=d.get("id", ""),
            content=d.get("content", ""),
            memory_type=d.get("memory_type", ""),
            status=d.get("status", ""),
            importance=d.get("importance", 0),
            confidence=d.get("confidence", 0.0),
            sensitivity=d.get("sensitivity", "low"),
            metadata=d.get("metadata", {}),
            raw=d,
        )


@dataclass
class AuditEvent:
    id: str
    action: str
    reason: str
    memory_id: str | None = None
    created_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> AuditEvent:
        return cls(
            id=d.get("id", ""),
            action=d.get("action", ""),
            reason=d.get("reason", ""),
            memory_id=d.get("memory_id"),
            created_at=d.get("created_at", ""),
            raw=d,
        )


@dataclass
class RetentionDecision:
    memory_id: str
    policy: str
    outcome: str
    eligible_for_deletion: bool
    blocked_by: list[str]
    reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> RetentionDecision:
        return cls(
            memory_id=d.get("memory_id", ""),
            policy=d.get("policy", ""),
            outcome=d.get("outcome", ""),
            eligible_for_deletion=d.get("eligible_for_deletion", False),
            blocked_by=list(d.get("blocked_by", [])),
            reason=d.get("reason", ""),
            raw=d,
        )
