"""Runner tests — dry-run/live/resume/randomisation (offline, stub only)."""

from __future__ import annotations

import json

from research.extraction_eval.config import ExperimentConfig, ProviderSpec
from research.extraction_eval.runner import execute, plan_runs, randomize

_CASE = {
    "case_id": "c1", "category": "single_memory", "difficulty": "easy",
    "conversation": [{"turn_id": "t1", "role": "user", "content": "Remember I like tea."}],
    "target_turn_id": "t1",
    "gold": {"expected_noop": False, "atoms": [{
        "atom_id": "c1_a", "memory_text": "User likes tea.", "memory_type": "preference",
        "operation": "create", "policy_disposition": "save", "source_turn_ids": ["t1"]}]},
}


def _config():
    return ExperimentConfig(
        name="t", dataset="unused", prompt_file="prompts/extraction_v1.txt", repetitions=2,
        seed=42, matching_version="v1", matching_threshold=0.85, pricing_file="configs/pricing.yaml",
        providers=[ProviderSpec("stub", "stub", False), ProviderSpec("gemini", "gemini-2.5-flash", True)],
        raw={"name": "t"},
    )


def _dataset(tmp_path, n=2):
    p = tmp_path / "cases.jsonl"
    p.write_text("\n".join(json.dumps({**_CASE, "case_id": f"c{i}"}) for i in range(n)) + "\n")
    return p


def test_dry_run_makes_no_calls_or_writes(tmp_path):
    ds = _dataset(tmp_path)
    out = tmp_path / "results"
    stats = execute(_config(), ds, out, live=False, dry_run=True)
    assert stats.executed == 0
    assert not (out / "raw").exists()  # dry-run writes nothing


def test_live_provider_skipped_without_live_flag(tmp_path):
    ds = _dataset(tmp_path)
    out = tmp_path / "results"
    stats = execute(_config(), ds, out, live=False)
    # stub runs (1 rep x 2 cases = 2); gemini (live) skipped.
    assert stats.executed == 2 and stats.skipped_not_live > 0
    runs = list((out / "raw").glob("*/runs.jsonl"))[0].read_text().splitlines()
    assert all(json.loads(r)["provider"] == "stub" for r in runs)


def test_resume_skips_completed(tmp_path):
    ds = _dataset(tmp_path)
    out = tmp_path / "results"
    execute(_config(), ds, out, live=False)
    stats2 = execute(_config(), ds, out, live=False)  # rerun
    assert stats2.executed == 0 and stats2.skipped_resume == 2  # nothing re-written


def test_randomisation_deterministic_under_seed(tmp_path):
    from research.extraction_eval.dataset import load_cases

    cases = load_cases(_dataset(tmp_path, n=5))
    plan = plan_runs(_config(), cases)
    a, _ = randomize(plan, 123)
    b, _ = randomize(plan, 123)
    assert [r.key() for r in a] == [r.key() for r in b]
    c, _ = randomize(plan, 999)
    assert [r.key() for r in a] != [r.key() for r in c]  # different seed -> different order


def test_order_is_interleaved_not_grouped_by_provider(tmp_path):
    from research.extraction_eval.dataset import load_cases

    cases = load_cases(_dataset(tmp_path, n=8))
    plan = plan_runs(_config(), cases)
    ordered, meta = randomize(plan, 42)
    providers_seq = [r.provider for r in ordered]
    # Not all of one provider before the other (interleaved).
    assert providers_seq != sorted(providers_seq, key=lambda p: p != "stub")
    assert meta["seed"] == 42
