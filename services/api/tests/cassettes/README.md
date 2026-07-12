# Recorded provider cassettes (P1.1)

VCR.py cassettes (via `pytest-recording`) that let CI replay **real** LLM-provider
responses deterministically, with no API key and no network.

## Recording a cassette (one time, with a key)

```bash
cd services/api
OPENAI_API_KEY=sk-...    pytest tests/test_provider_recorded.py::test_extraction_real_openai_multi    --record-mode=once
ANTHROPIC_API_KEY=sk-... pytest tests/test_provider_recorded.py::test_extraction_real_anthropic_multi --record-mode=once
```

This writes `<test_name>.yaml` here. The `authorization` / `x-api-key` headers are
scrubbed (see the `@pytest.mark.vcr(filter_headers=...)` on each test), so it is safe
to commit. Commit the `.yaml` files.

## Behavior without a cassette

The tests SKIP when neither a cassette nor the relevant API key is present, so the
default CI run stays green and offline. Once a cassette is committed, CI replays it
with `--record-mode=none` and the test runs for real.
