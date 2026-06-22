"""Background memory lifecycle workers (v0.6, ADR-010).

Tenant-scoped, idempotent, retry-safe maintenance that runs *outside* the chat
request path: decay, archive, deletion verification, conflict scan, and (optional,
off by default) reflection. Workers never resurrect deleted memory, never cross a
tenant boundary, always write audit evidence, and never block chat. The policy
broker stays authoritative — workers demote/flag/propose, they do not bypass
policy to create or promote active memory.

Public surface:
  * ``run_jobs`` / ``runner.main`` — execute selected jobs for a tenant/user scope.
  * ``WorkerContext`` — tenant-scoped execution context (injectable clock).
  * the individual ``*Worker`` classes and the ``WorkerJobResult`` /
    ``WorkerRunReport`` result types.
"""

from __future__ import annotations

from .archive import ArchiveWorker
from .conflict_scan import ConflictScanWorker
from .decay import DecayWorker
from .deletion_compaction import DeletionCompactionWorker
from .deletion_verification import DeletionVerificationWorker
from .lifecycle import LifecycleWorker, WorkerContext
from .metrics import summarize_compaction_results, summarize_worker_results
from .reflection import ReflectionWorker
from .runner import run_jobs
from .schemas import (
    PurgeVerification,
    WorkerJob,
    WorkerJobResult,
    WorkerRunReport,
    WorkerRunStatus,
)
from .vector_purge import PurgeCheck, verify_purged

__all__ = [
    "ArchiveWorker",
    "ConflictScanWorker",
    "DecayWorker",
    "DeletionCompactionWorker",
    "DeletionVerificationWorker",
    "LifecycleWorker",
    "PurgeCheck",
    "PurgeVerification",
    "ReflectionWorker",
    "WorkerContext",
    "WorkerJob",
    "WorkerJobResult",
    "WorkerRunReport",
    "WorkerRunStatus",
    "run_jobs",
    "summarize_compaction_results",
    "summarize_worker_results",
    "verify_purged",
]
