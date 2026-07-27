# Pilot execution guide

The 15-case pilot validates **plumbing only**: auth, connectivity, structured-output
reliability, schema parsing, token/latency accounting, error handling, file layout,
resume. It must **not** be used to select models, drop a model, alter labels, tune
provider-specific prompts, or change thresholds.

## Steps
```bash
# 1. Offline dry run — no API calls.
python -m research.extraction_eval.run --config configs/pilot.yaml --dry-run
# 2. Stub control (offline).
python -m research.extraction_eval.run --config configs/pilot.yaml --provider stub
# 3. One live provider at a time (costs money; needs the key).
GOOGLE_API_KEY=... python -m research.extraction_eval.run --config configs/pilot.yaml --provider gemini --live
OPENAI_API_KEY=... python -m research.extraction_eval.run --config configs/pilot.yaml --provider openai --live
ANTHROPIC_API_KEY=... python -m research.extraction_eval.run --config configs/pilot.yaml --provider anthropic --live
# 4. Inspect raw records + errors; re-run resumes (idempotent).
python -m research.extraction_eval.analyse --config configs/pilot.yaml
```
Check `results/raw/<exp>/errors.jsonl` for structured-output / refusal / truncation rates.
A pilot that surfaces these is doing its job — fix plumbing, not labels.
