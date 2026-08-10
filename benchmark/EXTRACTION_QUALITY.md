# Extraction quality (25 labeled turns)

| Provider | Precision | Recall | F1 | No-op handled | Multi-memory turns |
| --- | --- | --- | --- | --- | --- |
| stub | 1.00 | 0.53 | 0.69 | 3/3 | 4/9 |
| gemini-2.5-flash | 0.97 | 0.94 | 0.95 | 3/3 | 7/9 |

> **The gap is the point.** The offline **stub** is high-precision (1.00) but
> low-recall (0.53) and can only split **4 of 9** compound "multi-memory" turns — it
> misses roughly half the facts a real model captures. The recorded
> **gemini-2.5-flash** run reaches **0.97 precision / 0.94 recall / 0.95 F1**, handles
> all **3/3** no-op turns correctly, and splits **7 of 9** multi-memory turns. This is
> why the stub is a *reproducible test fixture, not the product*: it keeps CI offline
> and deterministic, but the flagship capability — governed extraction quality —
> requires a real model, and that is now measured and replayable rather than asserted.

## Recorded evidence

The Gemini row is not a remembered number. It is regenerated in CI from a committed
recording of a real provider run:

- **model:** `gemini-2.5-flash`
- **dataset:** 25 labeled turns (`evals/datasets/extraction_golden.jsonl`)
- **real provider interactions:** 25 (25 × HTTP 200)
- **structured outcomes:** 25
- **heuristic fallbacks:** 0
- **strict-empty fallbacks:** 0
- **provider errors:** 0
- **raw counts:** `tp=30`, `extracted=31`, `covered=32`, `expected=34`
- **cassette:** `services/api/tests/cassettes/test_extraction_quality_real_gemini.yaml`
- **replay:** requires **no** Gemini API key and **no** network access

Extraction *mode* is asserted, not inferred. `extract_memories` falls back to the
deterministic heuristic whenever a provider call fails (invariant #4), so a headline
"real provider" score can be partly stub while still issuing 25 HTTP requests. Every
turn is checked for `mode == "structured"`; 25 requests is not evidence of 25
structured extractions.

### What this does and does not claim

It claims the committed run **regenerates deterministically**: the same responses, the
same score, on any machine, with no credential.

It does **not** claim that a new live Gemini call will produce 0.97 / 0.94 / 0.95.
Hosted-model outputs can vary over time; a cassette is a record, not a forecast.

## Reproduce

Primary path — offline replay, no API key, no network:

```bash
cd services/api
pip install -r requirements-dev.txt
pip install ".[gemini]"
pytest tests/test_extraction_evidence_gemini.py --record-mode=none --block-network
```

The `google-genai` SDK is required (replay exercises the real Gemini adapter); a real
**credential** is not. This is what CI runs.

Score the offline stub for comparison:

```bash
PYTHONPATH=services/api python evals/run_extraction_quality.py --provider stub
```

### Optional maintenance: re-recording

Re-recording is **not** the reproduction path and is not run in CI. It needs a live
key, spends provider quota, and produces new provider outputs that may score
differently:

```bash
cd services/api
GEMINI_API_KEY=<set-in-environment> MEMORYOPS_LLM_PROVIDER=gemini GEMINI_MODEL=gemini-2.5-flash \
  pytest tests/test_extraction_evidence_gemini.py::test_extraction_quality_real_gemini \
  --record-mode=once
```

Do not overwrite the canonical cassette casually. A replacement recording changes the
published evidence and must be reviewed as such — including re-checking it for
credential material before it is committed (see `services/api/tests/cassettes/README.md`).

## Historical note

An earlier live `gemini-2.5-flash` run produced **0.94 precision / 0.94 recall /
0.94 F1**, with 3/3 no-op and 7/9 multi-memory. Its provider responses were not
recorded, so that run cannot be replayed. The committed recorded run above is
therefore the canonical reproducible evidence.

The earlier result is not invalid — it was a real observed measurement. It is simply
non-replayable, and superseded as canonical evidence by a run that can be re-executed.
The available artifacts do not establish the cause of the difference between the two
runs.
