"""Neutral benchmark harness for the governance-runtime study (paper Phase 2).

Public surface: the ``MemorySystemAdapter`` contract + the neutral result/capability/
manifest types. System adapters (S0, S0-U, S1–S4) and the runner build on these.
"""

from .adapter import MemorySystemAdapter
from .types import (
    Capability,
    EvidenceResult,
    ForgetResult,
    IngestResult,
    MemoryRef,
    OpStatus,
    Outcome,
    QueryResult,
    RunManifest,
    Scope,
    UpdateResult,
)

__all__ = [
    "MemorySystemAdapter",
    "Capability",
    "OpStatus",
    "Outcome",
    "Scope",
    "MemoryRef",
    "IngestResult",
    "QueryResult",
    "ForgetResult",
    "UpdateResult",
    "EvidenceResult",
    "RunManifest",
]
