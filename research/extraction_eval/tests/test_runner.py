"""Runner tests — dry-run/live/resume/randomisation (offline, stub only)."""

from __future__ import annotations

import json

from research.extraction_eval.config import ExperimentConfig, ProviderSpec
from research.extraction_eval.runner import build_schedule, execute, plan_runs

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


def test_schedule_deterministic_under_seed(tmp_path):
    from research.extraction_eval.dataset import load_cases

    cases = load_cases(_dataset(tmp_path, n=5))
    plan = plan_runs(_config(), cases)
    a, _ = build_schedule(plan, 123)
    b, _ = build_schedule(plan, 123)
    assert [r.key() for r in a] == [r.key() for r in b]
    c, _ = build_schedule(plan, 999)
    assert [r.key() for r in a] != [r.key() for r in c]  # different seed -> different order


def test_schedule_interleaves_providers_not_grouped(tmp_path):
    from research.extraction_eval.dataset import load_cases

    cases = load_cases(_dataset(tmp_path, n=8))
    plan = plan_runs(_config(), cases)  # stub + gemini(live)
    ordered, meta = build_schedule(plan, 42)
    seq = [r.provider for r in ordered]
    # No provider runs to completion before the other: the last stub appears AFTER the
    # first non-stub (they are interleaved, not blocked).
    first_nonstub = next(i for i, p in enumerate(seq) if p != "stub")
    last_stub = max(i for i, p in enumerate(seq) if p == "stub")
    assert last_stub > first_nonstub
    assert meta["strategy"] == "per_rep_case_shuffle+provider_rotation"


def test_case_order_shuffled_per_repetition(tmp_path):
    # With 5 reps, the case order within rep 1 differs from rep 2 (per-rep shuffle).
    from research.extraction_eval.config import ExperimentConfig, ProviderSpec
    from research.extraction_eval.dataset import load_cases

    cfg = ExperimentConfig(name="t", dataset="u", prompt_file="prompts/extraction_v1.txt", repetitions=5,
                           seed=7, matching_version="v1", matching_threshold=0.85,
                           pricing_file="configs/pricing.yaml",
                           providers=[ProviderSpec("gemini", "g", True)], raw={})
    cases = load_cases(_dataset(tmp_path, n=10))
    ordered, _ = build_schedule(plan_runs(cfg, cases), 7)
    rep1 = [r.case.case_id for r in ordered if r.repetition == 1]
    rep2 = [r.case.case_id for r in ordered if r.repetition == 2]
    assert rep1 != rep2  # order randomised per repetition


def test_final_design_plans_2400_runs():
    # 150 cases x (stub 1 + 3 live x 5 reps) = 150 + 2250 = 2400.
    from research.extraction_eval.config import ExperimentConfig, ProviderSpec
    from research.extraction_eval.schema import Case

    cfg = ExperimentConfig(name="final", dataset="u", prompt_file="prompts/extraction_v1.txt", repetitions=5,
                           seed=1, matching_version="v1", matching_threshold=0.85,
                           pricing_file="configs/pricing.yaml",
                           providers=[
                               ProviderSpec("stub", "stub", False), ProviderSpec("gemini", "g", True),
                               ProviderSpec("openai", "o", True), ProviderSpec("anthropic", "a", True),
                           ], raw={})
    cases = [Case.model_validate({**_CASE, "case_id": f"c{i}"}) for i in range(150)]
    plan = plan_runs(cfg, cases)
    assert len(plan) == 2400
    stub = sum(1 for p in plan if p.provider == "stub")
    live = sum(1 for p in plan if p.live)
    assert stub == 150 and live == 2250


def test_resume_reuses_persisted_schedule(tmp_path):
    ds = _dataset(tmp_path, n=4)
    out = tmp_path / "results"
    execute(_config(), ds, out, live=False)  # builds + persists schedule.json
    sched = list((out / "raw").glob("*/schedule.json"))
    assert sched, "schedule not persisted"
    order_before = sched[0].read_text()
    execute(_config(), ds, out, live=False)  # resume must reuse the same schedule
    assert sched[0].read_text() == order_before
