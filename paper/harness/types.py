"""Neutral result, capability, and manifest types for the benchmark harness.

System-agnostic by design: every system under test (governed MemoryOps `S0`, its
governance-disabled twin `S0-U`, and the external baselines `S1`–`S4`) is driven
through the same adapter and its per-operation results are described with the same
vocabulary, so scores are comparable and a *missing capability* is never silently
counted as a failure. See `paper/protocol.md` §5.

Two distinct enums, kept separate on purpose:

* ``OpStatus`` — what an *adapter operation* reports (`ok` / `unsupported` / `error`).
  The adapter never decides pass/fail; it reports whether the system could perform
  the operation at all.
* ``Outcome`` — the *case-level* classification a rubric produces
  (`pass` / `fail` / `unsupported` / `error`). The case evaluator maps
  ``OpStatus.unsupported`` → ``Outcome.unsupported`` and ``OpStatus.error`` →
  ``Outcome.error``; only an ``ok`` operation is graded pass/fail against the rubric.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OpStatus(str, Enum):
    """Whether an adapter could perform an operation (not whether it was correct)."""

    OK = "ok"
    UNSUPPORTED = "unsupported"  # the system has no such capability — a finding, not a fail
    ERROR = "error"  # crash / timeout / malformed output


class Outcome(str, Enum):
    """Case-level classification produced by a rubric (protocol §5)."""

    PASS = "pass"
    FAIL = "fail"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class Capability(str, Enum):
    """Operations a system may support. Declared by ``adapter.capabilities()`` and
    reconciled against actual op statuses by the contract tests."""

    INGEST = "ingest"
    QUERY = "query"
    FORGET = "forget"
    UPDATE = "update"
    EXPORT_EVIDENCE = "export_evidence"


@dataclass(frozen=True)
class Scope:
    """Tenant + user isolation boundary carried on every operation (invariant #1)."""

    tenant_id: str
    user_id: str


@dataclass
class MemoryRef:
    memory_id: str
    content: str | None = None
    score: float | None = None


@dataclass
class IngestResult:
    status: OpStatus
    memory_ids: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class QueryResult:
    status: OpStatus
    answer: str = ""
    used_memory_ids: list[str] = field(default_factory=list)
    retrieved: list[MemoryRef] = field(default_factory=list)
    detail: str = ""


@dataclass
class ForgetResult:
    status: OpStatus
    detail: str = ""


@dataclass
class UpdateResult:
    status: OpStatus
    detail: str = ""


@dataclass
class EvidenceResult:
    status: OpStatus
    available: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    detail: str = ""


@dataclass
class RunManifest:
    """Per-run provenance stamped into every result file (protocol §6/§10). No result
    number is trustworthy without the manifest that produced it. Fields are filled by
    the runner; unknowns stay empty rather than being guessed."""

    system: str  # e.g. "S0", "S0-U", "S2"
    benchmark_version: str
    git_sha: str
    model_id: str = ""
    provider: str = ""
    prompt_version: str = ""
    temperature: float | None = None
    seed: int | None = None
    storage_backend: str = ""
    vector_backend: str = ""
    timestamp: str = ""  # ISO-8601 UTC
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    error_count: int = 0
    fallback_count: int = 0
    env: dict[str, str] = field(default_factory=dict)  # python/lib versions

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)
