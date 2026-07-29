"""Analysis: raw run records → per-case scores → processed CSVs + statistics.json.

Every number is derived here from the immutable raw records; nothing is hand-entered.
Statistics are case-level (repetitions grouped) with a recorded bootstrap seed.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .config import ExperimentConfig
from .dataset import load_cases
from .reporting import to_csv
from .schema import ExtractionOutput
from .scoring import CaseScore, ScoringConfig, aggregate, score_case
from .statistics import descriptive, paired_f1_diff_ci, provider_f1_ci


def load_runs(raw_dir: str | Path) -> list[dict]:
    runs_path = Path(raw_dir) / "runs.jsonl"
    if not runs_path.exists():
        return []
    return [json.loads(line) for line in runs_path.read_text().splitlines() if line.strip()]


def score_runs(runs: list[dict], dataset_path: str | Path, *, threshold: float) -> list[CaseScore]:
    gold_by_id = {c.case_id: c.gold for c in load_cases(dataset_path)}
    cat_by_id = {c.case_id: c.category for c in load_cases(dataset_path)}
    cfg = ScoringConfig(threshold=threshold)
    scores: list[CaseScore] = []
    for rec in runs:
        cid = rec["case_id"]
        gold = gold_by_id.get(cid)
        if gold is None:
            continue
        output = None
        if rec.get("parsed_response") is not None:
            output = ExtractionOutput.model_validate(rec["parsed_response"])
        scores.append(score_case(
            output, gold, provider=rec["provider"], case_id=cid,
            category=cat_by_id.get(cid, "unknown"), repetition=rec["repetition"],
            error_class=rec.get("error_class"), cfg=cfg,
        ))
    return scores


def _case_score_row(s: CaseScore) -> dict:
    return {
        "case_id": s.case_id, "category": s.category, "provider": s.provider,
        "repetition": s.repetition, "scored": int(s.scored), "error_class": s.error_class or "",
        "tp": s.tp, "fp": s.fp, "fn": s.fn, "exact_set_match": int(s.exact_set_match),
        "precision": "" if s.precision is None else round(s.precision, 4),
        "recall": "" if s.recall is None else round(s.recall, 4),
        "f1": "" if s.f1 is None else round(s.f1, 4),
        "noop_correct": "" if s.noop_correct is None else int(s.noop_correct),
    }


def write_processed(
    scores: list[CaseScore], out_dir: str | Path, *, seed: int, matching_version: str
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "case_scores.csv").write_text(to_csv([_case_score_row(s) for s in scores]))

    by_provider: dict[str, list[CaseScore]] = defaultdict(list)
    for s in scores:
        by_provider[s.provider].append(s)

    prov_rows = []
    for p in sorted(by_provider):
        agg = aggregate(by_provider[p])
        ci = provider_f1_ci(by_provider[p], seed=seed)
        prov_rows.append({
            "provider": p, "n_scored": agg.n_scored, "n_errors": agg.n_errors,
            "precision": "" if agg.precision is None else round(agg.precision, 4),
            "recall": "" if agg.recall is None else round(agg.recall, 4),
            "f1": "" if agg.f1 is None else round(agg.f1, 4),
            "f1_case_ci_lo": round(ci.lo, 4), "f1_case_ci_hi": round(ci.hi, 4), "f1_cases": ci.n,
        })
    (out_dir / "provider_summary.csv").write_text(to_csv(prov_rows))

    # Paired provider comparisons (Holm handled at report time if p-values added).
    providers = sorted(by_provider)
    pairs = {}
    for i, a in enumerate(providers):
        for b in providers[i + 1:]:
            ci = paired_f1_diff_ci(by_provider[a], by_provider[b], seed=seed)
            pairs[f"{a}_vs_{b}"] = {"mean_diff": round(ci.mean, 4), "ci_lo": round(ci.lo, 4),
                                   "ci_hi": round(ci.hi, 4), "n_shared_cases": ci.n}

    stats = {
        "seed": seed,
        "matching_version": matching_version,
        "descriptive": descriptive(scores),
        "providers": prov_rows,
        "paired_f1_diff": pairs,
    }
    (out_dir / "statistics.json").write_text(json.dumps(stats, indent=2))
    return stats


def analyse_experiment(config: ExperimentConfig, dataset_path: str | Path, out_root: str | Path,
                       experiment_id: str) -> dict:
    raw_dir = Path(out_root) / "raw" / experiment_id
    processed_dir = Path(out_root) / "processed" / experiment_id
    runs = load_runs(raw_dir)
    scores = score_runs(runs, dataset_path, threshold=config.matching_threshold)
    return write_processed(scores, processed_dir, seed=config.seed, matching_version=config.matching_version)
