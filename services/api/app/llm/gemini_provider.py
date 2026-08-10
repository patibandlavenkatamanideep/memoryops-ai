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
* The new client speaks HTTP over ``httpx`` rather than gRPC, so provider traffic is
  recordable by the VCR/pytest-recording stack the repository already depends on.
  That is what makes real-provider extraction evidence reproducible in CI.
"""

from __future__ import annotations

from .providers import BaseNetworkProvider


class GeminiProvider(BaseNetworkProvider):
    name = "gemini"

    def _invoke(self, *, system: str, user: str, task: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=self._api_key,
            # Seconds -> milliseconds; see the module docstring.
            http_options=types.HttpOptions(timeout=int(self._timeout * 1000)),
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
