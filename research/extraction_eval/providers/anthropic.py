"""Anthropic provider adapter. Live path guarded by the SDK + ANTHROPIC_API_KEY.
Deterministic ``parse`` needs neither.
"""

from __future__ import annotations

import json
import os
import random
import time

from ..errors import ErrorClass, is_retryable
from .base import ProviderResult, parse_json_output


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, configured_model_id: str, *, max_retries: int = 3, max_tokens: int = 2048) -> None:
        self.configured_model_id = configured_model_id
        self._max_retries = max_retries
        self._max_tokens = max_tokens

    def available(self) -> bool:
        if not os.getenv("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return True

    def is_live(self) -> bool:
        return True

    def parse(self, raw_text: str):
        return parse_json_output(raw_text)

    def extract(self, *, prompt: str, conversation: list[dict], target_turn_id: str) -> ProviderResult:
        import anthropic

        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        user = json.dumps({"conversation": conversation, "target_turn_id": target_turn_id})
        attempt, history = 0, []
        while True:
            attempt += 1
            try:
                resp = client.messages.create(
                    model=self.configured_model_id,
                    max_tokens=self._max_tokens,
                    temperature=0,
                    system=prompt + "\nRespond with a single JSON object only.",
                    messages=[{"role": "user", "content": user}],
                )
                raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
                stop = getattr(resp, "stop_reason", "") or ""
                usage = getattr(resp, "usage", None)
                res = _result_from_raw(raw, self, stop)
                res.retry_count = attempt - 1
                res.error_history = history
                res.api_model_id = getattr(resp, "model", "") or self.configured_model_id
                res.response_id = getattr(resp, "id", "") or ""
                res.input_tokens = getattr(usage, "input_tokens", 0) or 0
                res.output_tokens = getattr(usage, "output_tokens", 0) or 0
                res.cached_tokens = getattr(usage, "cache_read_input_tokens", None)
                res.sdk_version = _sdk_version()
                return res
            except Exception as exc:  # noqa: BLE001
                ec = _classify_exception(exc)
                history.append(ec.value)
                if attempt <= self._max_retries and is_retryable(ec):
                    time.sleep(min(8.0, 2 ** (attempt - 1)) * (0.5 + random.random() / 2))  # noqa: S311
                    continue
                return ProviderResult(
                    error_class=ec.value, error_detail=type(exc).__name__,
                    retry_count=attempt - 1, error_history=history,
                    api_model_id=self.configured_model_id, sdk_version=_sdk_version(),
                )


def _result_from_raw(raw: str, provider, stop_reason: str) -> ProviderResult:
    if stop_reason == "max_tokens":
        return ProviderResult(
            raw_text=raw, error_class=ErrorClass.truncation.value, finish_reason=stop_reason
        )
    if stop_reason == "refusal":
        return ProviderResult(raw_text=raw, error_class=ErrorClass.refusal.value, finish_reason=stop_reason)
    output, err, detail = provider.parse(raw)
    return ProviderResult(output=output, raw_text=raw, finish_reason=stop_reason,
                          error_class=(err.value if err else None), error_detail=detail)


def _classify_exception(exc: Exception) -> ErrorClass:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "ratelimit" in name or "429" in msg:
        return ErrorClass.rate_limit_error
    if "timeout" in name or "connection" in name or "apiconnection" in name:
        return ErrorClass.network_error
    if "internalserver" in name or "overloaded" in name or "500" in msg or "529" in msg:
        return ErrorClass.provider_error
    return ErrorClass.unknown_error


def _sdk_version() -> str:
    try:
        import anthropic

        return getattr(anthropic, "__version__", "")
    except Exception:  # noqa: BLE001
        return ""
