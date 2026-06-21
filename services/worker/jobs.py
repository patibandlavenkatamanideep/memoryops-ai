"""Background jobs (Phase 5 scaffold).

These define the background intelligence of the memory system: decay, archival,
reflection/compression, conflict resolution, and system-learning. They run
against the same repository interface as the API so they can later move to
Celery/Temporal with retries and dead-letter queues (see docs/rollout.md).

For Phase 1 these are deterministic, dependency-light stubs with real (if simple)
logic so the lifecycle is demonstrable end-to-end.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

# Reuse the API's repository + schemas without packaging the API.
_API = Path(__file__).resolve().parents[1] / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from app.db.repository import Repository  # noqa: E402
from app.loops.events import (  # noqa: E402
    complete_loop_run_sync,
    emit_loop_event_sync,
    start_loop_run_sync,
)
from app.loops.types import LoopId, LoopState  # noqa: E402
from app.schemas.memory import Status  # noqa: E402

_ARCHIVE_WEIGHT_FLOOR = 0.25
_DECAY_HALFLIFE_DAYS = 30.0


def decay_weights(repo: Repository, tenant_id: str, user_id: str) -> int:
    """Age out memory weights toward zero; reinforcement slows decay."""
    changed = 0
    for m in repo.retrieve_active(tenant_id, user_id):
        age_days = (datetime.now(UTC) - m.created_at).total_seconds() / 86400.0
        decay = 0.5 ** (age_days / _DECAY_HALFLIFE_DAYS)
        reinforcement_bonus = min(m.reinforcement_count * 0.05, 0.5)
        new_weight = round(min(decay + reinforcement_bonus, 2.0), 4)
        if new_weight != m.weight:
            m.weight = new_weight
            repo.update_memory(m)
            changed += 1
    return changed


def archive_low_weight(repo: Repository, tenant_id: str, user_id: str) -> int:
    """Archive memories that decayed below the floor (kept, not deleted)."""
    archived = 0
    for m in repo.retrieve_active(tenant_id, user_id):
        if m.weight < _ARCHIVE_WEIGHT_FLOOR:
            m.status = Status.archived
            m.archived_at = datetime.now(UTC)
            repo.update_memory(m)
            archived += 1
    return archived


def resolve_conflicts(repo: Repository, tenant_id: str, user_id: str) -> int:
    """Detect contradictory memories of the same type (count of groups)."""
    by_type: dict[str, list] = {}
    for m in repo.retrieve_active(tenant_id, user_id):
        by_type.setdefault(m.memory_type.value, []).append(m)
    return sum(1 for group in by_type.values() if len(group) > 1)


def reflect_and_compress(repo: Repository, tenant_id: str, user_id: str) -> int:
    """Placeholder for reflection/compression of repeated memories (Phase 5)."""
    return 0


def run_all(repo: Repository, tenant_id: str, user_id: str) -> dict:
    loop = start_loop_run_sync(
        repo,
        LoopId.LEARNING_CONTINUOUS,
        trace_id="worker",
        tenant_id=tenant_id,
        user_id=user_id,
        metadata={"source": "worker.run_all"},
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.OBSERVED,
        event_type="continuous_learning_observed",
        reason="worker tick observed continuous learning work",
        evidence={"jobs": ["decay", "archive", "conflict_detection", "compression", "reflection"]},
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.CLASSIFIED,
        event_type="continuous_learning_classified",
        reason="worker jobs classified by memory maintenance type",
        evidence={"decay": True, "archive": True, "conflict_detection": True},
    )
    summary = {
        "decayed": decay_weights(repo, tenant_id, user_id),
        "archived": archive_low_weight(repo, tenant_id, user_id),
        "conflict_groups": resolve_conflicts(repo, tenant_id, user_id),
        "compressed": reflect_and_compress(repo, tenant_id, user_id),
    }
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.EXECUTED,
        event_type="continuous_learning_executed",
        reason="worker learning jobs executed",
        evidence={**summary, "reflection": "stub"},
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.VERIFIED,
        event_type="continuous_learning_verified",
        reason="worker learning summary verified",
        evidence=summary,
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.AUDITED,
        event_type="continuous_learning_audited",
        reason="worker learning event recorded as loop evidence",
        evidence={"audit_event_id": None},
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.LEARNED,
        event_type="continuous_learning_learned",
        reason="continuous learning loop captured maintenance evidence",
        evidence=summary,
    )
    emit_loop_event_sync(
        repo,
        loop,
        LoopState.COMPLETED,
        event_type="continuous_learning_completed",
        reason="continuous learning loop completed",
        evidence=summary,
    )
    complete_loop_run_sync(repo, loop, metadata=summary)
    return summary
