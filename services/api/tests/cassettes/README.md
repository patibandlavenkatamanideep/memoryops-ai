# Recorded provider cassettes

VCR.py cassettes (via `pytest-recording`) that let CI replay **real** LLM-provider
responses deterministically, with no API key and no network.

## Cassettes here

| Cassette | Test | Status |
|---|---|---|
| `test_extraction_quality_real_gemini.yaml` | `tests/test_extraction_evidence_gemini.py` | **required** — CI fails if missing or if it skips |
| *(none)* | `tests/test_provider_recorded.py` (OpenAI, Anthropic) | optional — those tests skip without a cassette or key |

## Replay (the normal path)

Offline, no credential, no network. This is what CI runs:

```bash
cd services/api
pip install -r requirements-dev.txt
pip install ".[gemini]"
pytest tests/test_extraction_evidence_gemini.py --record-mode=none --block-network
```

The provider **SDK** is required — replay exercises the real adapter, which is the
point. A real **credential** is not: provider construction only needs a non-empty
string, so the test injects an obvious non-secret placeholder.

## Recording (one-time, live, credential required)

Recording spends provider quota and produces new outputs that may score differently
from the committed run. It is deliberately not part of CI or the reproduction path.

```bash
cd services/api
GEMINI_API_KEY=<set-in-environment> MEMORYOPS_LLM_PROVIDER=gemini GEMINI_MODEL=gemini-2.5-flash \
  pytest tests/test_extraction_evidence_gemini.py::test_extraction_quality_real_gemini \
  --record-mode=once
```

## Credential filtering — what is actually scrubbed

Configured in the `vcr_config` fixture on the test module. Values are **removed**, not
masked; a partially masked key is still a leak.

Request headers:

- `x-goog-api-key` — how `google-genai` sends an API key
- `authorization` — its OAuth/token paths, and other providers' bearer credentials
- `x-api-key`, `api-key` — other provider conventions
- `x-goog-api-client` — client fingerprint, not a credential but not needed either

Query parameters:

- `key` — the Gemini REST API also accepts a query-string credential; filtered
  defensively even though the current SDK sends a header

> Do not assume `authorization` is the only credential surface. Inspect what the SDK
> actually sends before recording a new provider — for Gemini it is `x-goog-api-key`,
> and a filter list copied from another provider would have committed a live key.

## Before committing a cassette

`tests/test_extraction_evidence_gemini.py` enforces these automatically, and they run
in the base suite even where the provider SDK is absent:

- interaction count matches the dataset (retries would inflate it)
- every recorded response is HTTP 200 — a cassette of errors is not provider evidence
- no Google API-key-shaped string
- no bearer credential material
- no unsanitized `x-goog-api-key` / `authorization` / `x-api-key` / `api-key`
- no `key=` query credential
- **the cassette does not contain the live `GEMINI_API_KEY`**, compared directly
  against the environment when one is present — the value is never printed, only
  whether it appears

Also run the repository secret scan before staging:

```bash
gitleaks detect --no-git --source services/api/tests/cassettes/
```

If any credential material is found: **delete the cassette, do not commit it**, and
re-record with the filters corrected.

## Request matching

The Gemini cassette holds 25 interactions against the same endpoint. Matching includes
the **request body**, so replay pairs each prompt with its own recorded response.
Ordering alone would silently mis-pair prompts and responses if the suite were
reordered or partially run. Credential-bearing headers are deliberately not matched on.

## Cassette layout

Cassettes live flat in this directory. `pytest-recording` defaults to
`cassettes/<module>/<test>.yaml`; the Gemini test overrides `vcr_cassette_dir` to keep
the flat convention this directory already used.
