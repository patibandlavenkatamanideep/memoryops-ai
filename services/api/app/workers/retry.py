"""Retry / backoff policy for the worker runtime (v0.8, ADR-012).

A small, deterministic, dependency-free retry helper used by the orchestrator to
absorb *transient* infrastructure faults (e.g. a brief store/lease hiccup) around
a scope's work. It is intentionally not a queue: exhausted retries surface as a
dead-letter record, never a silent loss.

Note: lifecycle workers themselves never raise (they catch and record), so retry
here wraps the orchestration around them — the parts that touch the store.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with a ceiling. Deterministic (no jitter) for tests."""

    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    backoff_factor: float = 2.0
    max_delay_seconds: float = 30.0

    def delay_for(self, attempt: int) -> float:
        """Seconds to wait *before* retry ``attempt`` (1-based: the wait after the
        first failed try is ``delay_for(1)``)."""
        if attempt < 1:
            return 0.0
        delay = self.base_delay_seconds * (self.backoff_factor ** (attempt - 1))
        return min(delay, self.max_delay_seconds)


@dataclass
class RetryOutcome(Generic[T]):
    ok: bool
    attempts: int
    value: T | None = None
    error: str | None = None


def run_with_retry(
    fn: Callable[[], T],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> RetryOutcome[T]:
    """Call ``fn`` up to ``policy.max_attempts`` times, backing off between tries.

    Returns a ``RetryOutcome``: ``ok=True`` with the value on success, or
    ``ok=False`` with the last error type name after retries are exhausted. Never
    re-raises — the caller decides what to do with an exhausted outcome
    (dead-letter it).
    """
    attempts = 0
    last_error: str | None = None
    while attempts < policy.max_attempts:
        attempts += 1
        try:
            return RetryOutcome(ok=True, attempts=attempts, value=fn())
        except Exception as exc:  # noqa: BLE001 — transient faults are retried/dead-lettered
            last_error = type(exc).__name__
            if attempts < policy.max_attempts:
                sleep(policy.delay_for(attempts))
    return RetryOutcome(ok=False, attempts=attempts, error=last_error)
