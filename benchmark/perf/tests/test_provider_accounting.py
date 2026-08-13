"""Provider accounting must be exact, capped, and impossible to fake.

The load-bearing case is `test_a_stubbed_runtime_cannot_pass_as_live_evidence`: during
Phase C a run finished with clean latency, zero errors and zero provider calls,
because the cached gateway still held a stub. That artifact was indistinguishable from
a successful live run except for the call counter. These tests pin the guard that
turns it into a failure.

No network, no provider SDK, no credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from provider_accounting import (  # noqa: E402
    BudgetExceeded,
    LiveProviderNotWired,
    ProviderAccount,
    assert_live_provider_wired,
)


def _account(max_attempts=450, max_cost=2.00):
    return ProviderAccount(
        max_attempts=max_attempts,
        max_cost_usd=max_cost,
        price_input_per_m=0.30,
        price_output_per_m=2.50,
    )


class _Usage:
    def __init__(self, prompt=0, candidates=0, thoughts=0):
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates
        self.thoughts_token_count = thoughts


# ── logical vs physical ──────────────────────────────────────────────────────
def test_logical_and_physical_counts_are_separate():
    a = _account()
    a.record_logical_call()
    a.reserve_attempt()
    a.reserve_attempt()  # a retry of the same logical call
    assert a.logical_calls == 1
    assert a.physical_attempts == 2
    assert a.retries == 1


def test_a_clean_run_records_no_retries():
    a = _account()
    for _ in range(150):
        a.record_logical_call()
        a.reserve_attempt()
    assert (a.logical_calls, a.physical_attempts, a.retries) == (150, 150, 0)


# ── hard ceilings are enforced before the request goes out ───────────────────
def test_the_attempt_ceiling_refuses_rather_than_reports():
    a = _account(max_attempts=3)
    for _ in range(3):
        a.reserve_attempt()
    with pytest.raises(BudgetExceeded):
        a.reserve_attempt()
    assert a.physical_attempts == 3, "the refused attempt must not be counted"


def test_the_cost_ceiling_aborts():
    a = _account(max_cost=0.01)
    a.record_usage(_Usage(prompt=1_000_000, candidates=1_000_000))  # far over
    with pytest.raises(BudgetExceeded):
        a.reserve_attempt()
    assert a.aborted


def test_once_aborted_further_attempts_stay_refused():
    a = _account(max_attempts=1)
    a.reserve_attempt()
    with pytest.raises(BudgetExceeded):
        a.reserve_attempt()
    with pytest.raises(BudgetExceeded):
        a.reserve_attempt()
    assert a.physical_attempts == 1


# ── token and cost accounting ────────────────────────────────────────────────
def test_usage_accumulates_across_calls():
    a = _account()
    a.record_usage(_Usage(prompt=688, candidates=109, thoughts=200))
    a.record_usage(_Usage(prompt=100, candidates=10, thoughts=20))
    assert a.input_tokens == 788
    assert a.output_tokens == 119
    assert a.thinking_tokens == 220


def test_thinking_tokens_are_billed_as_output():
    """Visible response text understates billing on Gemini 2.5 Flash."""
    without = _account()
    without.record_usage(_Usage(prompt=1000, candidates=1000, thoughts=0))
    with_thinking = _account()
    with_thinking.record_usage(_Usage(prompt=1000, candidates=1000, thoughts=1000))
    assert with_thinking.estimated_cost_usd > without.estimated_cost_usd
    assert with_thinking.estimated_cost_usd == pytest.approx(
        1000 / 1e6 * 0.30 + 2000 / 1e6 * 2.50
    )


def test_missing_usage_is_tolerated():
    """A provider that reports no usage must not crash the run or invent tokens."""
    a = _account()
    a.record_usage(None)
    a.record_usage(_Usage())
    assert (a.input_tokens, a.output_tokens, a.thinking_tokens) == (0, 0, 0)
    assert a.estimated_cost_usd == 0.0


# ── the wiring guard ─────────────────────────────────────────────────────────
def test_a_stubbed_runtime_cannot_pass_as_live_evidence():
    """The Phase C failure, pinned: clean run, zero calls, published as live."""
    a = _account()

    def stubbed_request():
        return None  # never touches the provider

    with pytest.raises(LiveProviderNotWired):
        assert_live_provider_wired(a, stubbed_request)


def test_a_wired_runtime_passes_the_guard():
    a = _account()

    def live_request():
        a.record_logical_call()
        a.reserve_attempt()

    assert_live_provider_wired(a, live_request)
    assert a.logical_calls == 1


def test_the_guard_reports_the_cached_gateway_cause():
    a = _account()
    with pytest.raises(LiveProviderNotWired, match="lru_cached"):
        assert_live_provider_wired(a, lambda: None)


# ── serialization excludes secrets and user data ─────────────────────────────
def test_serialized_account_carries_only_counts():
    a = _account()
    a.record_logical_call()
    a.reserve_attempt()
    a.record_usage(_Usage(prompt=361, candidates=42, thoughts=69))
    out = a.as_dict()
    assert out["logical_calls"] == 1 and out["physical_attempts"] == 1
    assert out["total_tokens"] == 472
    assert set(out) == {
        "logical_calls", "physical_attempts", "retries", "input_tokens",
        "output_tokens", "thinking_tokens", "total_tokens", "estimated_cost_usd",
        "price_input_per_m_usd", "price_output_per_m_usd", "max_attempts",
        "max_cost_usd", "aborted", "error_classes",
    }


def test_errors_record_the_class_not_the_message():
    """A provider error message can echo the request; the class name cannot."""
    a = _account()
    secret = "sk" + "-" + "live" + "0123456789abcdef"
    a.record_error(ValueError(f"rejected request containing {secret}"))
    out = a.as_dict()
    assert out["error_classes"] == ["ValueError"]
    assert secret not in repr(out)


def test_serialized_account_has_no_credential_or_scope_fields():
    blob = repr(_account().as_dict()).lower()
    for forbidden in ("api_key", "authorization", "password", "tenant", "user_id", "prompt"):
        assert forbidden not in blob
