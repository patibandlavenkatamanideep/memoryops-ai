# Extraction-Quality Evaluation (research harness)

Provider-neutral, reproducible evaluation of memory-extraction quality across a
deterministic control and three live model families. Replaces the 25-turn single-model
pilot in the paper with a 150-case locked, 3-provider, 5-repetition study.

> **Research infrastructure — not the production request path.** Nothing here runs
> inside `services/api` chat handling. Pre-registration:
> [`paper/protocol-amendments/001-multi-provider-extraction-evaluation.md`](../../paper/protocol-amendments/001-multi-provider-extraction-evaluation.md).
> Frozen runtime subject: tag `paper-v0.1-governance-runtime` (never moved by this work).

## Vocabulary (read this first)

| Term | Meaning |
|------|---------|
| **Pilot integration run** | 15-case run that validates *plumbing* (auth, parsing, accounting) — **never** used for accuracy claims or model selection. |
| **Locked final run** | The scored study: 150 immutable cases × 3 live models × 5 reps + 1 stub/case. |
| **Deterministic control (stub)** | MemoryOps' offline heuristic, run once per case. An engineering control, **not** a live-model baseline. |
| **Live providers** | Gemini / OpenAI / Anthropic (exact model IDs in `configs/final.yaml`). |
| **Primary metric** | Deterministic atom precision/recall/F1 + exact-set match (no LLM judge). |
| **Secondary / sensitivity** | Optional semantic/embedding score — never replaces the primary. |
| **Human review** | ≥50 blinded locked cases, Cohen's kappa (a *target*, measured — not assumed). |
| **Unsupported / missing** | A capability a system lacks (reported separately, never a failure). |
| **Infrastructure error** | Our bug / transport failure (429/5xx/timeout) — retried. |
| **Model error** | Bad JSON / schema / refusal / truncation / empty — recorded, **not** retried. |

## Layout

```
schema.py          provider-neutral output + gold schema (canonical enums)
providers/         stub + gemini/openai/anthropic (import-guarded); base.parse() is offline
errors.py          error taxonomy + one retry policy (transport-only)
config.py          versioned experiment config (model ids, threshold, seed)
manifests.py       per-call record (§14) + experiment manifest
runner.py          execution (randomised, resumable, immutable, dry-run/live)
matching.py        deterministic bipartite atom matching (primary scorer)
scoring.py         per-case metrics (extraction vs disposition separate)
statistics.py      case-level bootstrap CIs + Holm (repetitions grouped)
reporting.py       CSV/MD/LaTeX tables + guarded figures
costs.py           pricing (null until verified) → estimated cost
human_review.py    blinded export/import + Cohen's kappa
dataset.py locking.py   authoring, validation, immutable lock + errata
run.py analyse.py build_paper_artifacts.py   CLIs
datasets/ results/ configs/ prompts/ tests/ docs/
```

## Quickstart (offline, no keys)

```bash
python -m research.extraction_eval.validate_dataset \
  --dataset research/extraction_eval/datasets/development/cases.jsonl
python -m research.extraction_eval.run    --config research/extraction_eval/configs/pilot.yaml --provider stub
python -m research.extraction_eval.analyse --config research/extraction_eval/configs/pilot.yaml
python -m research.extraction_eval.build_paper_artifacts --config research/extraction_eval/configs/pilot.yaml
```

Live runs require `--live` and the relevant key (`GOOGLE_API_KEY` / `OPENAI_API_KEY` /
`ANTHROPIC_API_KEY`). See the guides:

- [dataset authoring](docs/dataset_authoring.md) · [annotation](docs/annotation_guide.md)
- [provider setup](docs/provider_setup.md) · [pilot execution](docs/pilot_execution.md)
- [final execution checklist](docs/final_execution_checklist.md)
- [result interpretation](docs/result_interpretation.md) · [failure recovery](docs/failure_recovery.md)
- [paper update checklist](docs/paper_update_checklist.md)

## Integrity rules (enforced by the harness, not just documented)

- Model outputs never revise gold labels. Locked datasets are hash-protected and
  immutable (changes → new version + errata).
- Invalid model output is an outcome, never silently regenerated. No cross-provider
  fallback. The case (not the call) is the statistical unit.
- Prices are `null` until verified; no fabricated cost. No number is hand-typed into the
  paper — every table/figure derives from result files.
