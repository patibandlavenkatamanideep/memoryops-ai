"""Worker layer schemas + structured run results (v0.6).

These describe *what a worker did*, never *what a memory contains*. Worker results
and audit metadata carry ids, counts, and reasons only — no raw memory content,
secrets, or full user messages (mirrors the loop-metadata rule). Results are the
operational contract the runner/CLI returns and the API/metrics summarize.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum

# ── Job identifiers ───────────────────────────────────────────────────────────


class WorkerJob(str, Enum):
    decay = "decay"
    archive = "archive"
    deletion_compaction = "deletion_compaction"
    deletion_verification = "deletion_verification"
    conflict_scan = "conflict_scan"
    reflection = "reflection"


# Jobs the runner executes for the "all" selector, in a deliberate order:
# mutating jobs first, then compaction of already-deleted memory, and read-only
# verification last so it observes the state the mutating + compaction jobs left.
DEFAULT_JOB_ORDER: tuple[WorkerJob, ...] = (
    WorkerJob.decay,
    WorkerJob.archive,
    WorkerJob.conflict_scan,
    WorkerJob.reflection,
    WorkerJob.deletion_compaction,
    WorkerJob.deletion_verification,
)


# ── Vector / content purge verification outcomes (v0.7) ────────────────────────
# Honest result space. ``not_supported`` is reserved for a backend that genuinely
# cannot clear vector material; both shipped backends DO clear it, so a real
# deleted memory that is still reachable or whose material is intact is a ``fail``
# (fail-closed), never a silent pass.
class PurgeVerification(str, Enum):
    passed = "pass"
    failed = "fail"
    skipped = "skipped"
    not_supported = "not_supported"


# ── Run status ────────────────────────────────────────────────────────────────


class WorkerRunStatus(str, Enum):
    completed = "completed"
    completed_with_findings = "completed_with_findings"  # e.g. deletion leak found
    skipped = "skipped"  # job disabled / not applicable
    failed = "failed"  # unexpected error; never blocks chat


# ── Audit / structured event actions (invariant #7) ───────────────────────────
# Worker-emitted audit actions. Kept as constants so tests, metrics, and the PR
# gate reference one source of truth.
WORKER_STARTED = "lifecycle_worker_started"
WORKER_COMPLETED = "lifecycle_worker_completed"
WORKER_FAILED = "lifecycle_worker_failed"
MEMORY_DECAY_APPLIED = "memory_decay_applied"
MEMORY_ARCHIVE_CANDIDATE = "memory_archive_candidate"
MEMORY_ARCHIVED_BY_WORKER = "memory_archived_by_worker"
DELETION_VERIFICATION_PASSED = "deletion_verification_passed"
DELETION_VERIFICATION_FAILED = "deletion_verification_failed"
CONFLICT_CANDIDATE_DETECTED = "conflict_candidate_detected"
REFLECTION_CANDIDATE_DETECTED = "reflection_candidate_detected"
# v0.7 — physical deletion compaction + vector purge verification (ADR-011).
# These describe *what was cleared/verified*, never the cleared content itself.
DELETION_COMPACTION_STARTED = "deletion_compaction_started"
DELETION_COMPACTION_COMPLETED = "deletion_compaction_completed"
DELETION_COMPACTION_FAILED = "deletion_compaction_failed"
DELETION_COMPACTION_SKIPPED = "deletion_compaction_skipped"
MEMORY_CONTENT_COMPACTED = "memory_content_compacted"
MEMORY_VECTOR_PURGE_ATTEMPTED = "memory_vector_purge_attempted"
MEMORY_VECTOR_PURGE_VERIFIED = "memory_vector_purge_verified"
MEMORY_VECTOR_PURGE_FAILED = "memory_vector_purge_failed"
MEMORY_PURGE_TOMBSTONE_PRESERVED = "memory_purge_tombstone_preserved"

WORKER_AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        WORKER_STARTED,
        WORKER_COMPLETED,
        WORKER_FAILED,
        MEMORY_DECAY_APPLIED,
        MEMORY_ARCHIVE_CANDIDATE,
        MEMORY_ARCHIVED_BY_WORKER,
        DELETION_VERIFICATION_PASSED,
        DELETION_VERIFICATION_FAILED,
        CONFLICT_CANDIDATE_DETECTED,
        REFLECTION_CANDIDATE_DETECTED,
        DELETION_COMPACTION_STARTED,
        DELETION_COMPACTION_COMPLETED,
        DELETION_COMPACTION_FAILED,
        DELETION_COMPACTION_SKIPPED,
        MEMORY_CONTENT_COMPACTED,
        MEMORY_VECTOR_PURGE_ATTEMPTED,
        MEMORY_VECTOR_PURGE_VERIFIED,
        MEMORY_VECTOR_PURGE_FAILED,
        MEMORY_PURGE_TOMBSTONE_PRESERVED,
    }
)


# ── Structured results ────────────────────────────────────────────────────────


@dataclass
class WorkerJobResult:
    """The outcome of a single worker job within one tenant/user scope."""

    job: str
    tenant_id: str
    user_id: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str = WorkerRunStatus.completed.value
    scanned_count: int = 0
    changed_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    audit_event_ids: list[str] = field(default_factory=list)
    # Small, content-free operational detail (ids/counts/flags only).
    details: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def duration_ms(self) -> int:
        if self.completed_at is None:
            return 0
        return int((self.completed_at - self.started_at).total_seconds() * 1000)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["completed_at"] = self.completed_at.isoformat() if self.completed_at else None
        data["duration_ms"] = self.duration_ms
        return data


@dataclass
class WorkerRunReport:
    """Aggregate result of a runner invocation (one or more jobs/scopes)."""

    started_at: datetime
    completed_at: datetime | None = None
    results: list[WorkerJobResult] = field(default_factory=list)

    def add(self, result: WorkerJobResult) -> None:
        self.results.append(result)

    @property
    def scanned_count(self) -> int:
        return sum(r.scanned_count for r in self.results)

    @property
    def changed_count(self) -> int:
        return sum(r.changed_count for r in self.results)

    @property
    def skipped_count(self) -> int:
        return sum(r.skipped_count for r in self.results)

    @property
    def error_count(self) -> int:
        return sum(r.error_count for r in self.results)

    @property
    def ok(self) -> bool:
        """True when no job failed and no verification finding surfaced."""
        return all(
            r.status in (WorkerRunStatus.completed.value, WorkerRunStatus.skipped.value)
            for r in self.results
        )

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "ok": self.ok,
            "totals": {
                "scanned": self.scanned_count,
                "changed": self.changed_count,
                "skipped": self.skipped_count,
                "errors": self.error_count,
                "jobs": len(self.results),
            },
            "results": [r.to_dict() for r in self.results],
        }
