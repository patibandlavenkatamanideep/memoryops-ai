"""Worker run metrics helpers (v0.6).

Summarizes worker job results for the run status/metrics surface. Content-free:
counts and statuses only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from .schemas import WorkerJobResult, WorkerRunStatus


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
