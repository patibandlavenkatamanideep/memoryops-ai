# Provider LLM Adapters (v0.4)

MemoryOps AI has a provider-neutral LLM layer at
[services/api/app/llm/](../services/api/app/llm/). It lets the memory lifecycle
use real LLM reasoning (OpenAI, Anthropic, Gemini) for extraction, evaluation,
and conflict detection — while staying fully functional and test-safe with **no
API keys**. See [ADR-008](../infra/adr/ADR-008-provider-llm-adapters.md).

## The interface

```python
class LLMProvider(Protocol):
    name: str
    def complete(self, *, system: str, user: str, task: str = "general") -> str: ...
```

Synchronous, to match the synchronous read/write paths (consistent with the
embedding provider in ADR-006 and the compressor in ADR-007). Providers return
raw text; turning that into a validated structured object is the job of
`structured_output.py`.

## Providers

| Provider | Class | Used when |
| --- | --- | --- |
| Stub (default) | `StubProvider` | always available; deterministic, offline |
| OpenAI | `OpenAIProvider` | `MEMORYOPS_LLM_PROVIDER=openai` + `OPENAI_API_KEY` |
| Anthropic | `AnthropicProvider` | `MEMORYOPS_LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` |
| Gemini | `GeminiProvider` | `MEMORYOPS_LLM_PROVIDER=gemini` + `GEMINI_API_KEY` |

The registry (`registry.py`) selects from settings and **falls back to the stub**
whenever a networked provider is unconfigured (missing key) — so the app always
starts and CI never needs a secret. Networked SDKs are imported lazily, so the
package imports cleanly without `openai` / `anthropic` / `google-genai`
installed.

## Configuration

```bash
MEMORYOPS_LLM_PROVIDER=stub        # stub | openai | anthropic | gemini (default: stub)
MEMORYOPS_LLM_REQUIRE_STRUCTURED_OUTPUT=true
MEMORYOPS_LLM_FALLBACK_TO_HEURISTIC=true
MEMORYOPS_LLM_MAX_RETRIES=2
MEMORYOPS_LLM_TIMEOUT_SECONDS=20

OPENAI_API_KEY=        OPENAI_MODEL=gpt-4o-mini
ANTHROPIC_API_KEY=     ANTHROPIC_MODEL=claude-haiku-4-5-20251001
GEMINI_API_KEY=        GEMINI_MODEL=gemini-2.5-flash   # 1.5-flash retired
```

## Reliability & safety contract

- **Default is the stub.** Deterministic, offline, no key.
- **Failures never block chat.** A provider error, timeout, or invalid JSON
  degrades to the deterministic heuristic (invariant #4).
- **Structured output is schema-validated** before it is trusted; malformed JSON
  raises `StructuredOutputError` and triggers fallback.
- **LLM output is advisory.** The deterministic policy broker runs after
  extraction and stays authoritative — a model can never override policy, and
  secret-like content is still blocked (ADR-003/008).

### Retries are classified

`MEMORYOPS_LLM_MAX_RETRIES` is the budget for failures that could plausibly
succeed on an **identical retry**. It is not spent on failures that cannot.

| Outcome | Retried? | Attempts (`MAX_RETRIES=2`) |
|---|---|---|
| Connection / timeout (no response) | yes | up to 3 |
| `408` request timeout, `409` lock timeout | yes | up to 3 |
| `429` rate limit | yes | up to 3 |
| `5xx` server error | yes | up to 3 |
| `400` invalid request / `INVALID_ARGUMENT` | **no** | 1 |
| `401` authentication, `403` authorization | **no** | 1 |
| `404`, `413`, `422` | **no** | 1 |
| Local `ValueError` / `TypeError` / unknown | **no** | 1 |

The retryable status set is taken from the OpenAI and Anthropic SDKs' own
`_should_retry`, which is also why `408` and `409` are on it — both SDKs document
them as request timeout and lock timeout. `google-genai` retries a subset
(`429/500/502/503/504`).

Unknown exceptions **fail fast**. Retrying an unrecognised error is what this
rule exists to prevent: a recorded Gemini run configured below the API's minimum
deadline was rejected with a deterministic `400 INVALID_ARGUMENT`, and the old
retry-everything envelope turned 25 logical calls into 75 identical rejections
before degrading to the heuristic.

Classification changes only **how many attempts a failure costs**. Every failure
still normalises to `LLMUnavailableError` and still degrades to the deterministic
heuristic, so fallback behaviour is unchanged (invariant #4). Rules live in
`app/llm/errors.py`; `core.reliability.with_retry` takes the predicate and holds
no provider-specific knowledge.

## Observability

Events emitted through the redacting JSON logger (no secrets / keys / full user
messages): `llm_provider_call`, `llm_provider_failure`,
`structured_output_invalid`, `llm_fallback_used`, `memory_extraction_structured`,
`conflict_detection_result`.

## Tests

`test_llm_provider_registry.py`, `test_stub_llm_provider.py`,
`test_structured_memory_extraction.py`, `test_structured_output_validation.py`,
`test_llm_fallback.py`, `test_conflict_detection.py`,
`test_llm_provider_retry_classification.py` — none require an API key.

The retry-classification suite reconstructs each SDK's exception *shape* so it
runs with no provider extra installed, and additionally asserts the same
classification against the real `openai` / `anthropic` / `google-genai` exception
classes wherever those extras are present.
