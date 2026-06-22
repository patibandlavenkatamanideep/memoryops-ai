"""Worker run metrics helpers (v0.6).

Summarizes worker job results for the run status/metrics surface. Content-free:
counts and statuses only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from .schemas import WorkerJob, WorkerJobResult, WorkerRunStatus


def summarize_worker_results(results: Iterable[WorkerJobResult]) -> dict:
    results = list(results)
    by_status = Counter(r.status for r in results)
    by_job = Counter(r.job for r in results)
    return {
        "jobs": len(results),
        "by_status": dict(by_status),
        "by_job": dict(by_job),
        "scanned": sum(r.scanned_count for r in results),
        "changed": sum(r.changed_count for r in results),
        "skipped": sum(r.skipped_count for r in results),
        "errors": sum(r.error_count for r in results),
        "failed": by_status.get(WorkerRunStatus.failed.value, 0),
        "with_findings": by_status.get(WorkerRunStatus.completed_with_findings.value, 0),
    }


def summarize_compaction_results(results: Iterable[WorkerJobResult]) -> dict:
    """Roll up deletion-compaction lifecycle metrics (v0.7). Content-free counts.

    Sums the per-run ``details`` the compaction worker records so an operator/
    metrics surface can show purge progress without re-reading audit events.
    """
    compaction = [r for r in results if r.job == WorkerJob.deletion_compaction.value]

    def _sum(key: str) -> int:
        return sum(int(r.details.get(key, 0)) for r in compaction)

    return {
        "deletion_compaction_runs": len(compaction),
        "deletion_compaction_scanned_count": _sum("deleted_scanned"),
        "deletion_compaction_eligible_count": _sum("eligible_count"),
        "deletion_compaction_success_count": _sum("compacted_count"),
        "deletion_compaction_failure_count": _sum("failed_count"),
        "vector_purge_verified_count": _sum("verified_count"),
        "vector_purge_failed_count": _sum("failed_count"),
        "tombstone_preserved_count": _sum("tombstone_preserved_count"),
        "skipped_not_eligible_count": _sum("skipped_count"),
    }
