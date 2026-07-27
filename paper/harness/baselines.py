"""Ungoverned baseline adapters S1–S3 (protocol §3).

Deliberately simple, self-contained, offline systems that share MemoryOps' **LLM**
(`app.core.llm.get_llm().complete`) and **embeddings** (`app.embeddings.embed`) so the
model is held constant across systems (protocol §4) — the difference under test is the
memory + governance design, not the model.

- **S1 full-context** — keeps raw history, passes all of it to the model. The utility
  *ceiling* (no retrieval loss), not a persistent-memory governance baseline.
- **S2 plain-vector** — embed each message, cosine top-k, compose. Standard RAG memory.
- **S3 rolling-summary** — a single growing summary string. Compression baseline.

None have governance: they honestly return ``unsupported`` for capabilities they lack
(S1/S3 cannot forget/update a specific memory; none export governance evidence) — which
is exactly the capability-coverage signal H1 measures, never silently a failure.

Note: under the deterministic stub LLM the *answer text* is a fixed template, so utility
here is read from the **retrieved** memories (retrieval precision/recall); answer
correctness needs a real model (protocol §11). This module is experiment tooling; it
bridges to the frozen ``services/api`` app via a guarded ``sys.path`` insert.
"""

from __future__ import annotations

import itertools
import math
import sys
from pathlib import Path

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

_API = Path(__file__).resolve().parents[2] / "services" / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))


def _llm_answer(context: str, question: str) -> str:
    from app.core.llm import get_llm

    return get_llm().complete(system=context, user=question)


def _embed(text: str) -> list[float]:
    from app.embeddings import embed

    return embed(text)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _unsupported_forget() -> ForgetResult:
    return ForgetResult(status=OpStatus.UNSUPPORTED, detail="no addressable memory")


def _unsupported_update() -> UpdateResult:
    return UpdateResult(status=OpStatus.UNSUPPORTED, detail="no addressable memory")


def _no_evidence() -> EvidenceResult:
    return EvidenceResult(status=OpStatus.UNSUPPORTED, detail="ungoverned: no evidence")


class FullContextBaseline:
    """S1 — pass all history to the model (utility ceiling)."""

    name = "S1"

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], list[tuple[str, str]]] = {}
        self._ids = itertools.count(1)

    def capabilities(self) -> set[Capability]:
        return {Capability.INGEST, Capability.QUERY}

    def reset(self) -> None:
        self._store.clear()
        self._ids = itertools.count(1)

    def _bucket(self, s: Scope) -> list[tuple[str, str]]:
        return self._store.setdefault((s.tenant_id, s.user_id), [])

    def ingest(self, scope: Scope, message: str) -> IngestResult:
        mid = f"s1-{next(self._ids)}"
        self._bucket(scope).append((mid, message))
        return IngestResult(status=OpStatus.OK, memory_ids=[mid])

    def query(self, scope: Scope, question: str) -> QueryResult:
        items = self._bucket(scope)
        context = "\n".join(text for _, text in items)
        return QueryResult(
            status=OpStatus.OK,
            answer=_llm_answer(context, question),
            used_memory_ids=[mid for mid, _ in items],
            retrieved=[MemoryRef(memory_id=mid, content=text) for mid, text in items],
        )

    def forget(self, scope: Scope, memory_id: str) -> ForgetResult:
        return _unsupported_forget()

    def update(self, scope: Scope, memory_id: str, content: str) -> UpdateResult:
        return _unsupported_update()

    def export_evidence(self, scope: Scope) -> EvidenceResult:
        return _no_evidence()


class VectorBaseline:
    """S2 — embed, cosine top-k, compose. Standard RAG memory."""

    name = "S2"

    def __init__(self, *, top_k: int = 5) -> None:
        self._top_k = top_k
        self._store: dict[tuple[str, str], dict[str, tuple[str, list[float]]]] = {}
        self._ids = itertools.count(1)

    def capabilities(self) -> set[Capability]:
        return {Capability.INGEST, Capability.QUERY, Capability.FORGET, Capability.UPDATE}

    def reset(self) -> None:
        self._store.clear()
        self._ids = itertools.count(1)

    def _bucket(self, s: Scope) -> dict[str, tuple[str, list[float]]]:
        return self._store.setdefault((s.tenant_id, s.user_id), {})

    def ingest(self, scope: Scope, message: str) -> IngestResult:
        mid = f"s2-{next(self._ids)}"
        self._bucket(scope)[mid] = (message, _embed(message))
        return IngestResult(status=OpStatus.OK, memory_ids=[mid])

    def query(self, scope: Scope, question: str) -> QueryResult:
        qv = _embed(question)
        scored = [
            (mid, text, _cosine(qv, vec)) for mid, (text, vec) in self._bucket(scope).items()
        ]
        scored.sort(key=lambda t: t[2], reverse=True)
        top = scored[: self._top_k]
        context = "\n".join(text for _, text, _ in top)
        return QueryResult(
            status=OpStatus.OK,
            answer=_llm_answer(context, question),
            used_memory_ids=[mid for mid, _, _ in top],
            retrieved=[MemoryRef(memory_id=mid, content=text, score=sc) for mid, text, sc in top],
        )

    def forget(self, scope: Scope, memory_id: str) -> ForgetResult:
        self._bucket(scope).pop(memory_id, None)
        return ForgetResult(status=OpStatus.OK)

    def update(self, scope: Scope, memory_id: str, content: str) -> UpdateResult:
        bucket = self._bucket(scope)
        if memory_id not in bucket:
            return UpdateResult(status=OpStatus.ERROR, detail="unknown memory_id")
        bucket[memory_id] = (content, _embed(content))
        return UpdateResult(status=OpStatus.OK)

    def export_evidence(self, scope: Scope) -> EvidenceResult:
        return _no_evidence()


class SummaryBaseline:
    """S3 — a single rolling summary string. Compression baseline."""

    name = "S3"

    def __init__(self, *, max_chars: int = 4000) -> None:
        self._max = max_chars
        self._summary: dict[tuple[str, str], str] = {}

    def capabilities(self) -> set[Capability]:
        return {Capability.INGEST, Capability.QUERY}

    def reset(self) -> None:
        self._summary.clear()

    def ingest(self, scope: Scope, message: str) -> IngestResult:
        key = (scope.tenant_id, scope.user_id)
        # Offline-deterministic "summary": append and keep the most recent tail. A
        # real deployment would LLM-summarize; that is a real-model variant.
        merged = (self._summary.get(key, "") + "\n" + message).strip()
        self._summary[key] = merged[-self._max :]
        return IngestResult(status=OpStatus.OK)  # no addressable id

    def query(self, scope: Scope, question: str) -> QueryResult:
        context = self._summary.get((scope.tenant_id, scope.user_id), "")
        return QueryResult(status=OpStatus.OK, answer=_llm_answer(context, question))

    def forget(self, scope: Scope, memory_id: str) -> ForgetResult:
        return _unsupported_forget()

    def update(self, scope: Scope, memory_id: str, content: str) -> UpdateResult:
        return _unsupported_update()

    def export_evidence(self, scope: Scope) -> EvidenceResult:
        return _no_evidence()


def s1() -> FullContextBaseline:
    return FullContextBaseline()


def s2() -> VectorBaseline:
    return VectorBaseline()


def s3() -> SummaryBaseline:
    return SummaryBaseline()
