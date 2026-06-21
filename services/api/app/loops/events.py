"""Loop run/event helpers.

Async functions are the public contract requested by v0.2.2. The existing API
paths are synchronous, so thin sync wrappers are provided for integration.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from ..core.logging import get_logger
from ..db.repository import Repository
from .state_machine import validate_transition
from .types import LoopEvent, LoopId, LoopRun, LoopState, LoopStatus

logger = get_logger("memoryops.loops")

_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_-]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
    re.compile(r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*\S+"),
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def sanitize_loop_metadata(value: Any) -> Any:
    """Keep loop metadata structured and safe for operational traces."""
    if isinstance(value, dict):
        return {str(k): sanitize_loop_metadata(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_loop_metadata(v) for v in value]
    if isinstance(value, tuple):
        return [sanitize_loop_metadata(v) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    if len(text) > 160:
        text = text[:157] + "..."
    return text


async def start_loop_run(
    repo: Repository,
    loop_id: LoopId,
    trace_id: str,
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> LoopRun:
    run = LoopRun(
        id=str(uuid.uuid4()),
        loop_id=loop_id,
        trace_id=trace_id,
        tenant_id=tenant_id,
        user_id=user_id,
        status=LoopStatus.RUNNING,
        started_at=_now(),
        metadata=sanitize_loop_metadata(metadata or {}),
    )
    repo.add_loop_run(run)
    logger.info("loop run started", extra={"event": "loop_run_started", "loop_id": loop_id.value})
    return run


async def emit_loop_event(
    repo: Repository,
    run: LoopRun,
    state_to: LoopState,
    *,
    event_type: str,
    reason: str,
    state_from: LoopState | None = None,
    evidence: dict[str, Any] | None = None,
    audit_event_id: str | None = None,
) -> LoopEvent:
    previous = state_from
    if previous is None:
        prior = repo.list_loop_events(loop_run_id=run.id, limit=1)
        previous = prior[0].state_to if prior else None
    validate_transition(previous, state_to)
    event = LoopEvent(
        id=str(uuid.uuid4()),
        loop_run_id=run.id,
        loop_id=run.loop_id,
        trace_id=run.trace_id,
        state_from=previous,
        state_to=state_to,
        event_type=event_type,
        reason=reason,
        evidence=sanitize_loop_metadata(evidence or {}),
        audit_event_id=audit_event_id,
        created_at=_now(),
    )
    repo.add_loop_event(event)
    logger.info(
        reason,
        extra={
            "event": event_type,
            "loop_id": run.loop_id.value,
            "loop_state": state_to.value,
        },
    )
    return event


async def complete_loop_run(
    repo: Repository,
    run: LoopRun,
    *,
    metadata: dict[str, Any] | None = None,
) -> LoopRun:
    run.status = LoopStatus.COMPLETED
    run.ended_at = _now()
    run.metadata.update(sanitize_loop_metadata(metadata or {}))
    repo.update_loop_run(run)
    return run


async def fail_loop_run(
    repo: Repository,
    run: LoopRun,
    *,
    safe_degraded: bool = False,
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> LoopRun:
    run.status = LoopStatus.SAFE_DEGRADED if safe_degraded else LoopStatus.FAILED
    run.ended_at = _now()
    run.metadata.update(sanitize_loop_metadata({"reason": reason, **(metadata or {})}))
    repo.update_loop_run(run)
    return run


def start_loop_run_sync(
    repo: Repository,
    loop_id: LoopId,
    trace_id: str,
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> LoopRun:
    run = LoopRun(
        id=str(uuid.uuid4()),
        loop_id=loop_id,
        trace_id=trace_id,
        tenant_id=tenant_id,
        user_id=user_id,
        status=LoopStatus.RUNNING,
        started_at=_now(),
        metadata=sanitize_loop_metadata(metadata or {}),
    )
    repo.add_loop_run(run)
    return run


def emit_loop_event_sync(
    repo: Repository,
    run: LoopRun,
    state_to: LoopState,
    *,
    event_type: str,
    reason: str,
    evidence: dict[str, Any] | None = None,
    audit_event_id: str | None = None,
) -> LoopEvent:
    prior = repo.list_loop_events(loop_run_id=run.id, limit=1)
    state_from = prior[0].state_to if prior else None
    validate_transition(state_from, state_to)
    event = LoopEvent(
        id=str(uuid.uuid4()),
        loop_run_id=run.id,
        loop_id=run.loop_id,
        trace_id=run.trace_id,
        state_from=state_from,
        state_to=state_to,
        event_type=event_type,
        reason=reason,
        evidence=sanitize_loop_metadata(evidence or {}),
        audit_event_id=audit_event_id,
        created_at=_now(),
    )
    repo.add_loop_event(event)
    return event


def complete_loop_run_sync(
    repo: Repository,
    run: LoopRun,
    *,
    status: LoopStatus = LoopStatus.COMPLETED,
    metadata: dict[str, Any] | None = None,
) -> LoopRun:
    run.status = status
    run.ended_at = _now()
    run.metadata.update(sanitize_loop_metadata(metadata or {}))
    repo.update_loop_run(run)
    return run
