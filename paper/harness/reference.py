"""A trivial in-process reference adapter — a harness *self-test fixture*, not a
study baseline.

It exercises the ``MemorySystemAdapter`` contract end to end without any real model
or store: a per-scope dict of memories, naive substring recall, and **no** governance
evidence (so it drives the ``unsupported`` path for ``export_evidence``). The real
S0 / S0-U / S1–S4 adapters live elsewhere; this one only proves the contract and the
outcome vocabulary are coherent.
"""

from __future__ import annotations

import itertools

from .types import (
    Capability,
    EvidenceResult,
    ForgetResult,
    IngestResult,
    MemoryRef,
    OpStatus,
    QueryResult,
    Scope,
    UpdateResult,
)


class ReferenceDictAdapter:
    name = "reference"

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], dict[str, str]] = {}
        self._ids = itertools.count(1)

    def capabilities(self) -> set[Capability]:
        # Deliberately no EXPORT_EVIDENCE — an ungoverned reference has no audit.
        return {Capability.INGEST, Capability.QUERY, Capability.FORGET, Capability.UPDATE}

    def reset(self) -> None:
        self._store.clear()
        self._ids = itertools.count(1)

    def _scope(self, scope: Scope) -> dict[str, str]:
        return self._store.setdefault((scope.tenant_id, scope.user_id), {})

    def ingest(self, scope: Scope, message: str) -> IngestResult:
        mem_id = f"m{next(self._ids)}"
        self._scope(scope)[mem_id] = message
        return IngestResult(status=OpStatus.OK, memory_ids=[mem_id])

    def query(self, scope: Scope, question: str) -> QueryResult:
        terms = {w for w in question.lower().split() if len(w) > 3}
        hits = [
            MemoryRef(memory_id=mid, content=text)
            for mid, text in self._scope(scope).items()
            if terms & set(text.lower().split())
        ]
        answer = hits[0].content if hits else ""
        return QueryResult(
            status=OpStatus.OK,
            answer=answer or "",
            used_memory_ids=[h.memory_id for h in hits[:1]],
            retrieved=hits,
        )

    def forget(self, scope: Scope, memory_id: str) -> ForgetResult:
        self._scope(scope).pop(memory_id, None)
        return ForgetResult(status=OpStatus.OK)

    def update(self, scope: Scope, memory_id: str, content: str) -> UpdateResult:
        bucket = self._scope(scope)
        if memory_id not in bucket:
            return UpdateResult(status=OpStatus.ERROR, detail="unknown memory_id")
        bucket[memory_id] = content
        return UpdateResult(status=OpStatus.OK)

    def export_evidence(self, scope: Scope) -> EvidenceResult:
        # No governance layer → honestly unsupported (drives the separate-reporting path).
        return EvidenceResult(status=OpStatus.UNSUPPORTED, detail="no audit/evidence")
