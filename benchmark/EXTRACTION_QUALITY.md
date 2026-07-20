# Extraction quality (25 labeled turns)

| Provider | Precision | Recall | F1 | No-op handled | Multi-memory turns |
| --- | --- | --- | --- | --- | --- |
| stub | 1.00 | 0.53 | 0.69 | 3/3 | 4/9 |
| gemini-2.5-flash | 0.94 | 0.94 | 0.94 | 3/3 | 7/9 |

> **The gap is the point.** The offline **stub** is high-precision (1.00) but
> low-recall (0.53) and can only split **4 of 9** compound "multi-memory" turns — it
> misses roughly half the facts a real model captures. A real model (**gemini-2.5-flash**)
> nearly doubles recall to **0.94** and handles **7 of 9** multi-memory turns, at a
> small, honest precision cost (0.94 — it occasionally over-extracts). This is why the
> stub is a *reproducible test fixture, not the product*: it keeps CI offline and
> deterministic, but the flagship capability (governed extraction quality) requires a
> real model, and now that is measured rather than asserted.
>
> **Reproduce** (the gemini row was produced from a live run, 0 fallbacks):
> ```bash
> set -a; source .env; set +a           # GEMINI_API_KEY=...
> MEMORYOPS_LLM_PROVIDER=gemini GEMINI_MODEL=gemini-2.5-flash \
>   PYTHONPATH=services/api python evals/run_extraction_quality.py \
>   --provider stub gemini --md benchmark/EXTRACTION_QUALITY.md
> ```
> Runs offline for `stub`; `--provider openai anthropic gemini` fills in more rows
> when their keys are set. Note `gemini-1.5-flash` has been retired — use a current
> model (`gemini-2.5-flash`, `gemini-2.0-flash`, or `gemini-flash-latest`).
