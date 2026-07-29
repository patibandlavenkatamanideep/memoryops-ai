# Failure recovery guide

Raw records are append-only and immutable; re-running **resumes** (completed
(case, provider, repetition) keys are skipped), so interruption is safe.

| Symptom | Action |
|---------|--------|
| Run interrupted | Re-run the same command — resume skips completed keys. |
| 429 / 5xx / timeout | Retried automatically (≤3, backoff+jitter); retry count recorded. |
| Invalid JSON / schema / refusal / truncation / empty | Recorded as a model error in `errors.jsonl`; **not** retried. Do not hand-fix outputs. |
| Wrong prices | Fix `configs/pricing.yaml`; re-run `analyse`/`build_paper_artifacts` (scoring re-derives cost; no re-calls). |
| Dataset bug found post-lock | `append_errata` + mint a new dataset version; never edit the locked file. |
| Corrupt/partial record | Inspect `runs.jsonl`; delete only the offending line's key is not supported — prefer a fresh `experiment_id` and re-run. |
| Provider outage mid-run | Stop; resume later — no cross-provider fallback. |
