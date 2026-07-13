# Extraction quality (25 labeled turns)

| Provider | Precision | Recall | F1 | No-op handled | Multi-memory turns |
| --- | --- | --- | --- | --- | --- |
| stub | 1.00 | 0.53 | 0.69 | 3/3 | 4/9 |

> Regenerate: `python evals/run_extraction_quality.py --md benchmark/EXTRACTION_QUALITY.md`.
> The stub is the offline heuristic fixture; run `--provider openai anthropic`
> with keys to fill in real-model rows (the stub is expected to trail on recall
> and multi-memory turns — that gap is the honest signal).

