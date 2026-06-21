"""Loop metrics helpers."""

from __future__ import annotations

from collections import Counter

from .types import LoopRun, LoopStatus


def summarize_loop_runs(runs: list[LoopRun]) -> dict:
    by_status = Counter(r.status.value for r in runs)
    by_loop = Counter(r.loop_id.value for r in runs)
    failures = [
        r.metadata.get("failure_mode")
        for r in runs
        if r.status == LoopStatus.FAILED and r.metadata.get("failure_mode")
    ]
    failure_counts = Counter(str(f) for f in failures)
    most_common_failure = failure_counts.most_common(1)[0][0] if failure_counts else None
    return {
        "total_runs": len(runs),
        "by_status": dict(by_status),
        "by_loop": dict(by_loop),
        "failed": by_status.get(LoopStatus.FAILED.value, 0),
        "safe_degraded": by_status.get(LoopStatus.SAFE_DEGRADED.value, 0),
        "most_common_failure_mode": most_common_failure,
    }
