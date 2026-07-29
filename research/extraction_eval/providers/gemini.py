"""Google Gemini provider adapter (continuity model). Live path guarded by the SDK +
GOOGLE_API_KEY. Deterministic ``parse`` needs neither.
"""

from __future__ import annotations

import os
import random
import time

from ..errors import ErrorClass, is_retryable
from .base import ProviderResult, parse_json_output


class GeminiProvider:
    name = "gemini"

    def __init__(self, configured_model_id: str, *, max_retries: int = 3) -> None:
        self.configured_model_id = configured_model_id
        self._max_retries = max_retries

    def available(self) -> bool:
        if not os.getenv("GOOGLE_API_KEY"):
            return False
        try:
            from google import genai  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return True

    def is_live(self) -> bool:
        return True

    def parse(self, raw_text: str):
        return parse_json_output(raw_text)

    def extract(self, *, prompt: str, conversation: list[dict], target_turn_id: str) -> ProviderResult:
        import json

        from google import genai
        from google.genai import types

        client = genai.Client()  # reads GOOGLE_API_KEY
        user = json.dumps({"conversation": conversation, "target_turn_id": target_turn_id})
        attempt, history = 0, []
        while True:
            attempt += 1
            try:
                resp = client.models.generate_content(
                    model=self.configured_model_id,
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=prompt,
                        response_mime_type="application/json",
                        temperature=0,
                    ),
                )
                raw = getattr(resp, "text", "") or ""
                cand = (resp.candidates or [None])[0]
                finish = str(getattr(cand, "finish_reason", "")) if cand else ""
                usage = getattr(resp, "usage_metadata", None)
                res = _result_from_raw(raw, self, finish)
                res.retry_count = attempt - 1
                res.error_history = history
                res.api_model_id = getattr(resp, "model_version", "") or self.configured_model_id
                res.response_id = getattr(resp, "response_id", "") or ""
                res.input_tokens = getattr(usage, "prompt_token_count", 0) or 0
                res.output_tokens = getattr(usage, "candidates_token_count", 0) or 0
                res.cached_tokens = getattr(usage, "cached_content_token_count", None)
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


def _result_from_raw(raw: str, provider, finish_reason: str) -> ProviderResult:
    fr = (finish_reason or "").upper()
    if "MAX_TOKENS" in fr:
        return ProviderResult(raw_text=raw, error_class=ErrorClass.truncation.value, finish_reason=fr)
    if "SAFETY" in fr or "BLOCKLIST" in fr or "PROHIBITED" in fr:
        return ProviderResult(raw_text=raw, error_class=ErrorClass.refusal.value, finish_reason=fr)
    output, err, detail = provider.parse(raw)
    return ProviderResult(output=output, raw_text=raw, finish_reason=fr,
                          error_class=(err.value if err else None), error_detail=detail)


def _classify_exception(exc: Exception) -> ErrorClass:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "resourceexhausted" in name or "429" in msg or "rate" in msg:
        return ErrorClass.rate_limit_error
    if "deadline" in name or "timeout" in msg or "connection" in msg:
        return ErrorClass.network_error
    if "internal" in name or "unavailable" in name or "500" in msg or "503" in msg:
        return ErrorClass.provider_error
    return ErrorClass.unknown_error


def _sdk_version() -> str:
    try:
        import google.genai as g

        return getattr(g, "__version__", "")
    except Exception:  # noqa: BLE001
        return ""
