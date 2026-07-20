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
package imports cleanly without `openai` / `anthropic` / `google-generativeai`
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

## Observability

Events emitted through the redacting JSON logger (no secrets / keys / full user
messages): `llm_provider_call`, `llm_provider_failure`,
`structured_output_invalid`, `llm_fallback_used`, `memory_extraction_structured`,
`conflict_detection_result`.

## Tests

`test_llm_provider_registry.py`, `test_stub_llm_provider.py`,
`test_structured_memory_extraction.py`, `test_structured_output_validation.py`,
`test_llm_fallback.py`, `test_conflict_detection.py` — none require an API key.
