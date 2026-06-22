"""Worker retry / backoff policy (v0.8, ADR-012)."""

from __future__ import annotations

from app.workers.retry import RetryPolicy, run_with_retry


def test_delay_for_is_exponential_with_ceiling() -> None:
    p = RetryPolicy(base_delay_seconds=1.0, backoff_factor=2.0, max_delay_seconds=3.0)
    assert p.delay_for(1) == 1.0
    assert p.delay_for(2) == 2.0
    assert p.delay_for(3) == 3.0  # min(4, 3) — ceiling applied
    assert p.delay_for(0) == 0.0


def test_success_on_first_try_does_not_sleep() -> None:
    slept: list[float] = []
    out = run_with_retry(lambda: 42, RetryPolicy(max_attempts=3), sleep=slept.append)
    assert out.ok and out.value == 42 and out.attempts == 1
    assert slept == []


def test_retries_then_succeeds() -> None:
    calls = {"n": 0}
    slept: list[float] = []

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    out = run_with_retry(
        fn,
        RetryPolicy(max_attempts=3, base_delay_seconds=1.0, backoff_factor=2.0),
        sleep=slept.append,
    )
    assert out.ok and out.value == "ok" and out.attempts == 3
    assert slept == [1.0, 2.0]  # one wait after each of the first two failures


def test_exhausts_and_reports_last_error() -> None:
    slept: list[float] = []

    def fn() -> None:
        raise ValueError("always")

    out = run_with_retry(fn, RetryPolicy(max_attempts=2), sleep=slept.append)
    assert not out.ok
    assert out.attempts == 2
    assert out.error == "ValueError"
    assert len(slept) == 1  # no sleep after the final attempt
