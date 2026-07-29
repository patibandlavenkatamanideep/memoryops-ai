"""Case-level statistics tests — repetitions must not count as independent cases."""

from __future__ import annotations

from research.extraction_eval.scoring import CaseScore
from research.extraction_eval.statistics import (
    _percase_f1,
    bootstrap_ci,
    holm_correct,
    paired_f1_diff_ci,
    provider_f1_ci,
)


def _cs(case_id, rep, tp=1, fp=0, fn=0, provider="p"):
    return CaseScore(case_id=case_id, category="single_memory", provider=provider, repetition=rep,
                     tp=tp, fp=fp, fn=fn)


def test_repetitions_of_one_case_collapse_to_one_value():
    scores = [_cs("c1", r) for r in range(1, 6)]  # 5 reps of ONE case
    f1 = _percase_f1(scores)
    assert list(f1.keys()) == ["c1"]  # one case, not five
    assert f1["c1"] == 1.0


def test_bootstrap_ci_reproducible_under_seed():
    vals = [1.0, 0.5, 0.8, 0.0, 0.9, 0.6]
    a = bootstrap_ci(vals, seed=123)
    b = bootstrap_ci(vals, seed=123)
    assert (a.mean, a.lo, a.hi) == (b.mean, b.lo, b.hi)
    assert a.lo <= a.mean <= a.hi


def test_provider_f1_ci_uses_case_count_not_run_count():
    # 3 cases x 4 reps = 12 runs, but n should be 3 cases.
    scores = [_cs(f"c{c}", r) for c in range(3) for r in range(4)]
    ci = provider_f1_ci(scores, seed=1)
    assert ci.n == 3


def test_paired_diff_over_shared_cases():
    a = [_cs("c1", 1, tp=1), _cs("c2", 1, tp=1)]  # F1 = 1.0 each
    b = [_cs("c1", 1, tp=1, fp=1), _cs("c2", 1, tp=1, fp=1)]  # precision .5 -> F1 .667
    ci = paired_f1_diff_ci(a, b, seed=7)
    assert ci.n == 2 and ci.mean > 0


def test_holm_correction_monotone():
    adj = holm_correct({"a": 0.01, "b": 0.04, "c": 0.2})
    assert adj["a"] <= adj["b"] <= adj["c"]
    assert all(0.0 <= v <= 1.0 for v in adj.values())
