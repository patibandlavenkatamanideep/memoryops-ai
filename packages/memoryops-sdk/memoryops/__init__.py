"""MemoryOps AI — Python SDK.

A thin, typed client over the MemoryOps AI HTTP API. The server stays the source
of truth for governance (tenant isolation, policy-before-storage, the deletion
guarantee, legal hold, auditability); the SDK just makes the governed API easy to
call from assistants, agents, and RAG apps.

    from memoryops import MemoryOpsClient

    with MemoryOpsClient("http://localhost:8000", "tenant_demo", "user_demo") as mo:
        print(mo.chat("Remember I prefer metric units.").assistant_message)
"""

from __future__ import annotations

from .client import MemoryOpsClient
from .errors import APIError, LegalHoldError, MemoryOpsError, NotFoundError
from .models import (
    AuditEvent,
    CandidateDecision,
    ChatResult,
    Memory,
    RetentionDecision,
    UsedMemory,
)

__version__ = "0.11.0"

__all__ = [
    "MemoryOpsClient",
    "MemoryOpsError",
    "APIError",
    "NotFoundError",
    "LegalHoldError",
    "ChatResult",
    "Memory",
    "UsedMemory",
    "CandidateDecision",
    "AuditEvent",
    "RetentionDecision",
    "__version__",
]
