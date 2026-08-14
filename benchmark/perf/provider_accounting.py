"""Benchmark-only provider call accounting for live-provider experiments (Phase C).

Separates the two counts a live experiment must never conflate:

* **logical calls** — how many times the system asked the provider for a completion
* **physical attempts** — how many HTTP requests actually went out

They differ whenever the retry envelope re-attempts a call, so a budget expressed in
one is not a budget in the other. Both are enforced *before* an attempt leaves, so a
ceiling cannot be crossed and then noticed.

The wiring assertion
--------------------
`assert_live_provider_wired` exists because of a real failure during Phase C. The app
resolves its provider through `deps.gateway()`, which is `@lru_cache`d, so the Gateway
captures its provider on first use; rebinding the registry afterwards left the cached
instance on the previous provider. A run then completed with clean latency numbers,
zero errors — and zero provider calls, having measured the stub while claiming to
measure the provider. Silence looked exactly like success.

So a live run must *prove* the provider is wired before spending budget: issue one
request and require the call counter to move. If live evidence is requested and the
runtime is stubbed, this raises. It never silently continues.

Content safety
--------------
Only counts, token totals and exception *class names* are recorded. API keys, prompts,
memory content, embeddings and raw provider responses are never captured, so a
serialized artifact carries no secret and no user data.
"""

from __future__ import annotations

import threading


class LiveProviderNotWired(RuntimeError):
    """Live evidence was requested but the runtime did not call the provider."""


class BudgetExceeded(RuntimeError):
    """An attempt was refused because it would breach an approved ceiling."""


class ProviderAccount:
    """Counts calls/attempts/tokens and enforces hard ceilings.

    ``max_attempts`` and ``max_cost_usd`` are abort thresholds, not targets.
    """

    def __init__(
        self,
        *,
        max_attempts: int,
        max_cost_usd: float,
        price_input_per_m: float,
        price_output_per_m: float,
    ) -> None:
        self._lock = threading.Lock()
        self.max_attempts = max_attempts
        self.max_cost_usd = max_cost_usd
        self.price_input_per_m = price_input_per_m
        self.price_output_per_m = price_output_per_m
        self.logical_calls = 0
        self.physical_attempts = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.thinking_tokens = 0
        self.error_classes: list[str] = []
        self.aborted: str | None = None

    # ── accounting ───────────────────────────────────────────────────────────
    @property
    def retries(self) -> int:
        return self.physical_attempts - self.logical_calls

    @property
    def estimated_cost_usd(self) -> float:
        """Thinking tokens bill as output on Gemini 2.5 Flash, so they are priced
        as output rather than ignored — visible response text understates billing."""
        billed_output = self.output_tokens + self.thinking_tokens
        return (
            self.input_tokens / 1_000_000 * self.price_input_per_m
            + billed_output / 1_000_000 * self.price_output_per_m
        )

    def record_logical_call(self) -> None:
        with self._lock:
            self.logical_calls += 1

    def reserve_attempt(self) -> None:
        """Account for one outgoing HTTP attempt, or refuse it.

        Called *before* the request is sent so a ceiling is enforced rather than
        merely observed after the fact.
        """
        with self._lock:
            if self.aborted:
                raise BudgetExceeded(self.aborted)
            if self.physical_attempts + 1 > self.max_attempts:
                self.aborted = f"physical attempts would exceed {self.max_attempts}"
                raise BudgetExceeded(self.aborted)
            if self._cost_locked() >= self.max_cost_usd:
                self.aborted = (
                    f"estimated cost {self._cost_locked():.4f} reached "
                    f"ceiling {self.max_cost_usd}"
                )
                raise BudgetExceeded(self.aborted)
            self.physical_attempts += 1

    def _cost_locked(self) -> float:
        billed_output = self.output_tokens + self.thinking_tokens
        return (
            self.input_tokens / 1_000_000 * self.price_input_per_m
            + billed_output / 1_000_000 * self.price_output_per_m
        )

    def record_usage(self, usage) -> None:
        """Read token counts off a provider usage object. Missing fields count 0."""
        if usage is None:
            return
        with self._lock:
            self.input_tokens += int(getattr(usage, "prompt_token_count", 0) or 0)
            self.output_tokens += int(getattr(usage, "candidates_token_count", 0) or 0)
            self.thinking_tokens += int(getattr(usage, "thoughts_token_count", 0) or 0)

    def record_error(self, exc: BaseException) -> None:
        """Record the exception *class*; never its message, which may echo a request."""
        with self._lock:
            self.error_classes.append(type(exc).__name__)

    # ── serialization ────────────────────────────────────────────────────────
    def as_dict(self) -> dict:
        return {
            "logical_calls": self.logical_calls,
            "physical_attempts": self.physical_attempts,
            "retries": self.retries,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
            "total_tokens": self.input_tokens + self.output_tokens + self.thinking_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
            "price_input_per_m_usd": self.price_input_per_m,
            "price_output_per_m_usd": self.price_output_per_m,
            "max_attempts": self.max_attempts,
            "max_cost_usd": self.max_cost_usd,
            "aborted": self.aborted,
            "error_classes": sorted(set(self.error_classes)),
        }


def assert_live_provider_wired(account: ProviderAccount, issue_one_request) -> None:
    """Prove the live provider is reachable from the request path before spending.

    ``issue_one_request`` performs a single ordinary request. If the account's call
    counter does not move, the runtime is not calling the provider — most likely a
    cached gateway still holding a stub — and this raises rather than letting a
    stubbed run be published as live evidence.
    """
    before = account.logical_calls
    issue_one_request()
    if account.logical_calls <= before:
        raise LiveProviderNotWired(
            "live provider evidence was requested but the runtime made no provider "
            "call. The gateway is likely cached with a different provider "
            "(deps.gateway is lru_cached) — clear it after rebinding."
        )
