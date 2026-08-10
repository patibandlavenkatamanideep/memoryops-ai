"""Google Gemini provider (v0.4).

Used only when ``GEMINI_API_KEY`` is set and ``MEMORYOPS_LLM_PROVIDER=gemini``.
The ``google-genai`` SDK is imported lazily. Any failure propagates as
``LLMUnavailableError`` and the caller degrades to the deterministic heuristic.

Migrated from the retired ``google-generativeai`` SDK, whose import now prints
"All support for the `google.generativeai` package has ended". Two consequences of
the move are load-bearing rather than cosmetic:

* ``HttpOptions.timeout`` is expressed in **milliseconds**, while the old SDK's
  ``request_options={"timeout": …}`` took seconds. Passing the configured seconds
  through unchanged would have turned an 8-second budget into 8 milliseconds and
  failed every call.
* The deadline is now **sent to the server**, which enforces a 10-second minimum.
  Under gRPC it was applied client-side, so the repository's 8-second default was
  accepted; over REST it is rejected with ``400 INVALID_ARGUMENT`` and every call
  degrades to the heuristic. See ``GEMINI_MIN_DEADLINE_SECONDS``.
* The new client speaks HTTP over ``httpx`` rather than gRPC, so provider traffic is
  recordable by the VCR/pytest-recording stack the repository already depends on.
  That is what makes real-provider extraction evidence reproducible in CI.
"""

from __future__ import annotations

from .providers import BaseNetworkProvider

#: Gemini's REST API rejects a manually supplied deadline below this, with
#: ``400 INVALID_ARGUMENT: Manually set deadline 8s is too short. Minimum allowed
#: deadline is 10s``. The retired gRPC SDK applied the deadline client-side only, so
#: the repository's 8-second default worked and this constraint was invisible; the
#: REST transport sends it to the server, which validates it.
#:
#: Provider-local on purpose. It is a Gemini API rule, not a MemoryOps policy, so
#: `llm_timeout_seconds` keeps its meaning for OpenAI and Anthropic.
GEMINI_MIN_DEADLINE_SECONDS = 10.0


class GeminiProvider(BaseNetworkProvider):
    name = "gemini"

    def _invoke(self, *, system: str, user: str, task: str) -> str:
        from google import genai
        from google.genai import types

        # Raise the configured deadline to Gemini's floor; never lower a longer one.
        effective_timeout_seconds = max(self._timeout, GEMINI_MIN_DEADLINE_SECONDS)

        client = genai.Client(
            api_key=self._api_key,
            # Seconds -> milliseconds; see the module docstring.
            http_options=types.HttpOptions(timeout=int(effective_timeout_seconds * 1000)),
        )
        resp = client.models.generate_content(
            model=self._model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0,
            ),
        )
        return resp.text or ""
