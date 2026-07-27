"""Execution engine (§10, §13, §14).

Drives providers over cases × repetitions with: randomised, seed-recorded order
(never all of one provider then the next); append-only immutable raw records; resume
that skips completed (case, provider, repetition) keys; a dry-run that makes no API
call; and a hard requirement that live providers run only under an explicit ``live``
flag. No provider ever falls back to another.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import ExperimentConfig
from .costs import estimate_cost, load_pricing
from .dataset import load_cases
from .locking import sha256_text
from .manifests import CallRecord, ExperimentManifest
from .providers import build_provider
from .schema import Case


@dataclass
class PlannedRun:
    provider: str
    model_id: str
    live: bool
    case: Case
    repetition: int

    def key(self) -> tuple[str, str, int]:
        return (self.case.case_id, self.provider, self.repetition)


def plan_runs(config: ExperimentConfig, cases: list[Case]) -> list[PlannedRun]:
    plan: list[PlannedRun] = []
    for spec in config.providers:
        reps = config.repetitions if spec.live else 1  # control runs once (§13)
        for case in cases:
            for r in range(1, reps + 1):
                plan.append(PlannedRun(spec.name, spec.model_id, spec.live, case, r))
    return plan


def randomize(plan: list[PlannedRun], seed: int) -> tuple[list[PlannedRun], dict]:
    """Shuffle case order per repetition and rotate provider order; record the seed."""
    rng = random.Random(seed)
    ordered = list(plan)
    rng.shuffle(ordered)  # global shuffle interleaves providers + cases + reps
    return ordered, {"seed": seed, "strategy": "global_shuffle", "n": len(ordered)}


def experiment_id(config: ExperimentConfig, dataset_hash: str) -> str:
    return f"{config.name}-{dataset_hash[:8]}"


def _completed_keys(runs_path: Path) -> set[tuple[str, str, int]]:
    keys: set[tuple[str, str, int]] = set()
    if runs_path.exists():
        for line in runs_path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            keys.add((rec["case_id"], rec["provider"], rec["repetition"]))
    return keys


@dataclass
class RunStats:
    planned: int = 0
    executed: int = 0
    skipped_resume: int = 0
    skipped_not_live: int = 0
    errors: int = 0


def execute(
    config: ExperimentConfig,
    dataset_path: str | Path,
    out_root: str | Path,
    *,
    live: bool = False,
    dry_run: bool = False,
    only_provider: str | None = None,
    only_cases: set[str] | None = None,
    resume: bool = True,
) -> RunStats:
    cases = load_cases(dataset_path)
    if only_cases:
        cases = [c for c in cases if c.case_id in only_cases]
    dataset_hash = sha256_text(Path(dataset_path).read_text())
    exp_id = experiment_id(config, dataset_hash)
    raw_dir = Path(out_root) / "raw" / exp_id

    prompt_text = config.prompt_text()
    prompt_hash = config.prompt_hash()
    try:
        pricing = load_pricing(_resolve(config, config.pricing_file))
    except Exception:  # noqa: BLE001 — pricing optional; unverified → None cost
        pricing = {}

    plan = plan_runs(config, cases)
    if only_provider:
        plan = [p for p in plan if p.provider == only_provider]
    ordered, rand_meta = randomize(plan, config.seed)

    manifest = ExperimentManifest(
        experiment_id=exp_id, config_name=config.name, dataset_hash=dataset_hash,
        prompt_hash=prompt_hash, seed=config.seed, repetitions=config.repetitions,
        providers=[p.name for p in config.providers],
        model_ids={p.name: p.model_id for p in config.providers},
        matching_version=config.matching_version, matching_threshold=config.matching_threshold,
        pricing_version=str(pricing.get("pricing_version", "")),
        randomization=rand_meta,
    )

    runs_path = raw_dir / "runs.jsonl"
    errors_path = raw_dir / "errors.jsonl"
    stats = RunStats(planned=len(ordered))

    if dry_run:
        # No API calls, no writes at all; just report the plan.
        stats.skipped_not_live = sum(1 for p in ordered if p.live and not live)
        return stats

    # Write experiment provenance once.
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest.write(raw_dir / "manifest.json")
    (raw_dir / "prompt.txt").write_text(prompt_text)
    (raw_dir / "config.snapshot.yaml").write_text(_dump_yaml(config.raw))
    (raw_dir / "dataset.manifest.json").write_text(json.dumps(
        {"dataset_path": str(dataset_path), "sha256": dataset_hash, "n_cases": len(cases)}, indent=2))

    completed = _completed_keys(runs_path) if resume else set()
    for run in ordered:
        if run.live and not live:
            stats.skipped_not_live += 1
            continue
        if run.key() in completed:
            stats.skipped_resume += 1
            continue
        provider = build_provider(run.provider, run.model_id)
        conversation = [t.model_dump() for t in run.case.conversation]
        start = datetime.now(UTC)
        t0 = time.monotonic()
        result = provider.extract(prompt=prompt_text, conversation=conversation,
                                  target_turn_id=run.case.target_turn_id)
        latency = time.monotonic() - t0
        end = datetime.now(UTC)
        cost = estimate_cost(pricing, run.provider, result.input_tokens, result.output_tokens)
        rec = CallRecord(
            experiment_id=exp_id, case_id=run.case.case_id, category=run.case.category,
            repetition=run.repetition, provider=run.provider, configured_model_id=run.model_id,
            api_model_id=result.api_model_id, prompt_hash=prompt_hash, dataset_hash=dataset_hash,
            repo_commit=manifest.repo_commit, runtime_commit=manifest.runtime_commit,
            start_time=start.isoformat(), end_time=end.isoformat(), latency_s=round(latency, 6),
            input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            cached_tokens=result.cached_tokens, retry_count=result.retry_count,
            response_id=result.response_id, raw_response=result.raw_text,
            parsed_response=(result.output.model_dump() if result.output else None),
            schema_validation=("ok" if result.output else (result.error_class or "unknown_error")),
            error_class=result.error_class, estimated_cost_usd=(cost or 0.0),
            sdk_version=result.sdk_version,
        )
        with runs_path.open("a") as fh:
            fh.write(rec.to_json_line() + "\n")
        if result.error_class:
            with errors_path.open("a") as fh:
                fh.write(json.dumps({"case_id": run.case.case_id, "provider": run.provider,
                                     "repetition": run.repetition, "error_class": result.error_class,
                                     "detail": result.error_detail, "history": result.error_history}) + "\n")
            stats.errors += 1
        completed.add(run.key())
        stats.executed += 1
    return stats


def _resolve(config: ExperimentConfig, rel: str) -> Path:
    base = Path(__file__).resolve().parent
    p = Path(rel)
    return p if p.is_absolute() else base / rel


def _dump_yaml(data: dict) -> str:
    try:
        import yaml

        return yaml.safe_dump(data, sort_keys=False)
    except Exception:  # noqa: BLE001
        return json.dumps(data, indent=2)
