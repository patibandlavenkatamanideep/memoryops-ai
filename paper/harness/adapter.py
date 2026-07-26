"""The neutral ``MemorySystemAdapter`` contract (protocol §3, Phase 2).

Every system under test implements this Protocol so the runner can give each the
*identical* conversation history, scope, mutation sequence, and query set, and score
them with the identical rubric. The adapter is a thin, honest wrapper: it performs an
operation and reports an ``OpStatus`` — it does **not** grade correctness, and it must
report ``OpStatus.unsupported`` (never fake a success or a failure) for a capability
the underlying system genuinely lacks.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import (
    Capability,
    EvidenceResult,
    ForgetResult,
    IngestResult,
    QueryResult,
    Scope,
    UpdateResult,
)


@runtime_checkable
class MemorySystemAdapter(Protocol):
    #: Short stable id used in result manifests / tables (e.g. "S0", "S0-U", "S2").
    name: str

    def capabilities(self) -> set[Capability]:
        """The operations this system genuinely supports. An operation whose
        capability is absent must return ``OpStatus.unsupported`` (reconciled by the
        contract tests) — it is a reported finding, not a failure."""
        ...

    def reset(self) -> None:
        """Return the system to a clean, empty state so cases do not leak into one
        another. Must be idempotent."""
        ...

    def ingest(self, scope: Scope, message: str) -> IngestResult:
        """Offer a message to the system's memory pipeline for the given scope."""
        ...

    def query(self, scope: Scope, question: str) -> QueryResult:
        """Answer a question for the scope using whatever memory the system holds."""
        ...

    def forget(self, scope: Scope, memory_id: str) -> ForgetResult:
        """Delete a specific memory. ``unsupported`` if the system cannot forget."""
        ...

    def update(self, scope: Scope, memory_id: str, content: str) -> UpdateResult:
        """Replace a memory's content. ``unsupported`` if the system cannot update."""
        ...

    def export_evidence(self, scope: Scope) -> EvidenceResult:
        """Return governance/audit evidence for the scope, or ``unsupported`` if the
        system produces none."""
        ...
