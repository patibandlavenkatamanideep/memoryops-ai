"""The load harness must fail closed rather than publish a misleading number.

Every case here pins a way the harness previously *could* report a plausible result
for a run that measured something other than the request path. These are cheap to
get wrong and expensive to notice: a perf artifact carries no signal that its
latency distribution was contaminated, so the guard has to live in the harness.

No server is started. `_run_scenario` is driven against a fake client that returns
scripted statuses, which is what makes "a 500 must not enter the percentiles"
checkable at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_perf import (  # noqa: E402
    RATE_LIMITED_STATUS,
    _aggregate,
    _pct,
    _run_scenario,
)


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeClient:
    """Returns scripted statuses, with a distinct delay per outcome.

    Failures are made *slow* on purpose. The bug this suite guards against averaged
    failure latency into the success percentiles, and a slow failure is the case
    where that visibly corrupts the tail.
    """

    def __init__(self, statuses: list[int], ok_delay: float = 0.0, fail_delay: float = 0.02):
        self._statuses = list(statuses)
        self._ok_delay = ok_delay
        self._fail_delay = fail_delay
        self._i = 0

    def post(self, _url: str, json: dict | None = None) -> _FakeResponse:
        import time

        status = self._statuses[self._i % len(self._statuses)]
        self._i += 1
        if status == 0:  # transport failure
            time.sleep(self._fail_delay)
            raise RuntimeError("simulated transport failure")
        time.sleep(self._ok_delay if 200 <= status < 300 else self._fail_delay)
        return _FakeResponse(status)


def _scenario(statuses: list[int], *, rate_limit_mode: bool = False, concurrency: int = 1):
    client = _FakeClient(statuses)
    return _run_scenario(
        client, "retrieval", concurrency, len(statuses), 0, "t", "u", 10, 10,
        rate_limit_mode=rate_limit_mode,
    )


# ── latency distribution is success-only ─────────────────────────────────────
def test_successful_latencies_populate_the_percentiles():
    res = _scenario([200] * 10)
    assert res.successes == 10
    assert res.p50_ms is not None and res.p50_ms >= 0.0
    assert res.failed_n == 0


def test_a_500_does_not_enter_the_success_percentiles():
    """The failures are ~20ms; the successes are ~0ms."""
    res = _scenario([200] * 8 + [500] * 2)
    assert res.successes == 8
    assert res.failed_n == 2
    assert res.errors == 2
    # If failure latency leaked in, max would sit up at the ~20ms failure delay.
    assert res.max_ms is not None and res.max_ms < 10.0
    assert res.failed_p50_ms is not None and res.failed_p50_ms > 10.0


def test_a_transport_failure_does_not_enter_the_success_percentiles():
    res = _scenario([200] * 8 + [0] * 2)
    assert res.successes == 8
    assert res.failed_n == 2
    assert res.status_counts.get("0") == 2
    assert res.max_ms is not None and res.max_ms < 10.0


def test_failure_latency_is_reported_separately_but_never_mixed():
    res = _scenario([200] * 5 + [503] * 5)
    assert res.p50_ms is not None and res.failed_p50_ms is not None
    assert res.failed_p50_ms > res.p50_ms


# ── a scenario with no successes has no latency ──────────────────────────────
def test_zero_success_scenario_reports_no_latency_rather_than_zero():
    """0.0 would render as the fastest scenario in the sweep."""
    res = _scenario([500] * 6)
    assert res.successes == 0
    assert res.p50_ms is None and res.p95_ms is None and res.p99_ms is None
    assert res.min_ms is None and res.mean_ms is None and res.max_ms is None
    assert res.successful_rps == 0.0
    assert res.valid is False
    assert "no successful requests" in res.invalid_reason


def test_percentile_of_an_empty_distribution_is_none():
    assert _pct([], 0.5) is None
    assert _pct([], 0.95) is None


# ── throughput semantics ─────────────────────────────────────────────────────
def test_attempted_and_successful_rps_differ_when_requests_fail():
    res = _scenario([200] * 5 + [500] * 5)
    assert res.attempted_rps > res.successful_rps > 0
    # The back-compatible alias must track useful work, not offered load.
    assert res.rps == res.successful_rps


def test_attempted_and_successful_rps_agree_when_nothing_fails():
    res = _scenario([200] * 10)
    assert res.attempted_rps == res.successful_rps == res.rps


# ── rate limiting fails closed ───────────────────────────────────────────────
def test_a_single_429_invalidates_an_ordinary_performance_run():
    """The defect this prevents: a 429-heavy run sat under --max-error-rate and
    published limiter latency as request-path evidence."""
    res = _scenario([200] * 99 + [RATE_LIMITED_STATUS])
    assert res.rate_limited == 1
    assert res.valid is False
    assert "rate-limited" in res.invalid_reason


def test_a_rejection_heavy_run_is_invalid_even_though_it_looks_fast():
    res = _scenario([RATE_LIMITED_STATUS] * 70 + [200] * 30)
    assert res.valid is False
    assert res.rate_limited == 70


def test_rate_limit_mode_is_an_explicit_opt_in_and_stays_labelled():
    res = _scenario([RATE_LIMITED_STATUS] * 70 + [200] * 30, rate_limit_mode=True)
    assert res.valid is True, "explicit limiter measurement is legitimate"
    assert res.rate_limited == 70, "the 429 count stays visible, not laundered"
    assert res.successes == 30
    assert res.successful_rps < res.attempted_rps


def test_a_fully_rejected_run_is_valid_only_in_explicit_limiter_mode():
    """A saturated limiter rejects everything — that is the observation, not a fault.

    It still has no latency distribution, so the percentiles stay null rather than
    becoming 0.0. Outside limiter mode the same run is invalid.
    """
    saturated = [RATE_LIMITED_STATUS] * 30
    deliberate = _scenario(saturated, rate_limit_mode=True)
    assert deliberate.valid is True
    assert deliberate.successes == 0
    assert deliberate.p50_ms is None, "no successes means no latency, in any mode"
    assert deliberate.successful_rps == 0.0
    assert deliberate.attempted_rps > 0.0

    assert _scenario(saturated).valid is False


def test_a_clean_run_is_valid():
    res = _scenario([200] * 20)
    assert res.valid is True and res.invalid_reason is None


# ── seed semantics are truthful ──────────────────────────────────────────────
def test_seed_request_count_is_not_presented_as_a_memory_count():
    """`--seed-per-scenario` counts requests; the policy broker decides what is
    stored, so the resulting store size is measured, not assumed."""
    client = _FakeClient([200] * 4)
    res = _run_scenario(client, "retrieval", 1, 4, 0, "t", "u", 50, 7)
    assert res.seed_requests == 50, "seed requests are recorded as requests"
    assert res.memories_before == 7, "actual store size is measured independently"
    assert res.seed_requests != res.memories_before
    # Legacy field retained for artifact compatibility, same value.
    assert res.seed_count == res.seed_requests


# ── aggregation ──────────────────────────────────────────────────────────────
def test_invalid_repetitions_are_excluded_from_the_medians_but_stay_counted():
    good = _scenario([200] * 10)
    bad = _scenario([RATE_LIMITED_STATUS] * 10)
    agg = _aggregate([good, bad])[0]
    assert agg["repetitions"] == 2
    assert agg["valid_repetitions"] == 1
    assert agg["invalid_repetitions"] == 1
    assert agg["rate_limited_total"] == 10
    assert agg["p50_ms_median"] == good.p50_ms, "the invalid repetition must not shift it"


def test_aggregate_reports_no_latency_when_every_repetition_is_invalid():
    bad = _scenario([500] * 5)
    agg = _aggregate([bad, bad])[0]
    assert agg["valid_repetitions"] == 0
    assert agg["p50_ms_median"] is None
    assert agg["successful_rps_median"] is None


# ── percentile interpolation is unchanged ────────────────────────────────────
@pytest.mark.parametrize(
    ("vals", "p", "expected"),
    [
        ([1.0, 2.0, 3.0, 4.0], 0.0, 1.0),
        ([1.0, 2.0, 3.0, 4.0], 1.0, 4.0),
        ([1.0, 2.0, 3.0, 4.0], 0.5, 2.5),
        ([10.0], 0.95, 10.0),
        ([1.0, 2.0], 0.5, 1.5),
    ],
)
def test_percentile_interpolation_is_correct(vals, p, expected):
    assert _pct(vals, p) == pytest.approx(expected)


def test_percentiles_are_ordered_on_a_realistic_distribution():
    res = _scenario([200] * 50)
    assert res.min_ms <= res.p50_ms <= res.p95_ms <= res.p99_ms <= res.max_ms
