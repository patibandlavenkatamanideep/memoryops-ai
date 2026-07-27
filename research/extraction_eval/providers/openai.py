"""OpenAI provider adapter. Live path guarded behind the SDK + OPENAI_API_KEY.

Credentials are read from the environment only, never printed/persisted/committed. The
deterministic ``parse`` path (tested against recorded fixtures) needs neither.
"""

from __future__ import annotations

import os
import time

from ..errors import ErrorClass, is_retryable
from .base import ProviderResult, parse_json_output


class OpenAIProvider:
    name = "openai"

    def __init__(self, configured_model_id: str, *, max_retries: int = 3) -> None:
        self.configured_model_id = configured_model_id
        self._max_retries = max_retries

    def available(self) -> bool:
        if not os.getenv("OPENAI_API_KEY"):
            return False
        try:
            import openai  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return True

    def is_live(self) -> bool:
        return True

    def parse(self, raw_text: str):
        return parse_json_output(raw_text)

    def extract(self, *, prompt: str, conversation: list[dict], target_turn_id: str) -> ProviderResult:
        # Never runs without an explicit --live path + key; kept correct + guarded.
        import openai  # local import so module import needs no SDK

        client = openai.OpenAI()  # reads OPENAI_API_KEY from env
        user = _render_user(conversation, target_turn_id)
        attempt, history = 0, []
        while True:
            attempt += 1
            try:
                t0 = time.monotonic()
                resp = client.chat.completions.create(
                    model=self.configured_model_id,
                    messages=[{"role": "system", "content": prompt},
                              {"role": "user", "content": user}],
                    response_format={"type": "json_object"},
                    temperature=0,
                )
                latency = time.monotonic() - t0
                choice = resp.choices[0]
                raw = choice.message.content or ""
                finish = choice.finish_reason or ""
                usage = resp.usage
                res = _result_from_raw(raw, self, finish)
                res.retry_count = attempt - 1
                res.error_history = history
                res.api_model_id = getattr(resp, "model", "") or self.configured_model_id
                res.response_id = getattr(resp, "id", "")
                res.input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                res.output_tokens = getattr(usage, "completion_tokens", 0) or 0
                res.sdk_version = _sdk_version()
                res.error_detail = res.error_detail or f"latency={latency:.3f}s"
                return res
            except Exception as exc:  # noqa: BLE001
                ec = _classify_exception(exc)
                history.append(ec.value)
                if attempt <= self._max_retries and is_retryable(ec):
                    time.sleep(_backoff(attempt))
                    continue
                return ProviderResult(
                    error_class=ec.value, error_detail=type(exc).__name__,
                    retry_count=attempt - 1, error_history=history,
                    api_model_id=self.configured_model_id, sdk_version=_sdk_version(),
                )


def _render_user(conversation: list[dict], target_turn_id: str) -> str:
    import json

    return json.dumps({"conversation": conversation, "target_turn_id": target_turn_id})


def _result_from_raw(raw: str, provider, finish_reason: str) -> ProviderResult:
    if finish_reason == "length":
        return ProviderResult(raw_text=raw, error_class=ErrorClass.truncation.value,
                              finish_reason=finish_reason)
    if finish_reason in ("content_filter", "refusal"):
        return ProviderResult(raw_text=raw, error_class=ErrorClass.refusal.value,
                              finish_reason=finish_reason)
    output, err, detail = provider.parse(raw)
    return ProviderResult(
        output=output, raw_text=raw, finish_reason=finish_reason,
        error_class=(err.value if err else None), error_detail=detail,
    )


def _classify_exception(exc: Exception) -> ErrorClass:
    name = type(exc).__name__.lower()
    if "ratelimit" in name:
        return ErrorClass.rate_limit_error
    if "timeout" in name or "connection" in name or "apiconnection" in name:
        return ErrorClass.network_error
    if "internalserver" in name or "apistatus" in name or "500" in str(exc):
        return ErrorClass.provider_error
    return ErrorClass.unknown_error


def _backoff(attempt: int) -> float:
    import random

    return min(8.0, (2 ** (attempt - 1))) * (0.5 + random.random() / 2)  # noqa: S311


def _sdk_version() -> str:
    try:
        import openai

        return getattr(openai, "__version__", "")
    except Exception:  # noqa: BLE001
        return ""
