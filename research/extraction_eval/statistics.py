"""Case-level statistics (§17).

The **case** is the independent unit. Repetitions of one case are collapsed to a single
per-case value *before* resampling, so 2,250 calls are never treated as 2,250
independent samples. Confidence intervals are case bootstraps under a fixed, recorded
seed; paired comparisons resample the shared cases and difference the two providers.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from .scoring import CaseScore


def _percase_f1(scores: list[CaseScore]) -> dict[str, float]:
    """One F1 per case for a provider, micro-averaged over that case's repetitions.

    No-op cases contribute their no-op correctness (1.0/0.0) so they are represented;
    errored repetitions are dropped from that case's aggregation."""
    by_case: dict[str, list[CaseScore]] = defaultdict(list)
    for s in scores:
        by_case[s.case_id].append(s)
    out: dict[str, float] = {}
    for cid, reps in by_case.items():
        scored = [s for s in reps if s.scored]
        if not scored:
            continue  # all reps errored → case has no accuracy value
        if scored[0].expected_noop:
            out[cid] = sum(1.0 if s.noop_correct else 0.0 for s in scored) / len(scored)
            continue
        tp = sum(s.tp for s in scored)
        fp = sum(s.fp for s in scored)
        fn = sum(s.fn for s in scored)
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        out[cid] = (2 * p * r / (p + r)) if (p + r) else 0.0
    return out


@dataclass
class CI:
    mean: float
    lo: float
    hi: float
    n: int


def bootstrap_ci(values: list[float], *, seed: int, n_boot: int = 2000, alpha: float = 0.05) -> CI:
    if not values:
        return CI(float("nan"), float("nan"), float("nan"), 0)
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return CI(sum(values) / n, lo, hi, n)


def provider_f1_ci(scores: list[CaseScore], *, seed: int, n_boot: int = 2000) -> CI:
    return bootstrap_ci(list(_percase_f1(scores).values()), seed=seed, n_boot=n_boot)


def paired_f1_diff_ci(
    scores_a: list[CaseScore], scores_b: list[CaseScore], *, seed: int, n_boot: int = 2000,
    alpha: float = 0.05,
) -> CI:
    """Bootstrap CI for mean per-case F1 difference (A − B) over the shared cases."""
    fa, fb = _percase_f1(scores_a), _percase_f1(scores_b)
    shared = sorted(set(fa) & set(fb))
    diffs = [fa[c] - fb[c] for c in shared]
    return bootstrap_ci(diffs, seed=seed, n_boot=n_boot, alpha=alpha)


def holm_correct(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm–Bonferroni adjusted p-values for a family of paired comparisons."""
    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(items)
    adjusted: dict[str, float] = {}
    running = 0.0
    for i, (key, p) in enumerate(items):
        val = min(1.0, (m - i) * p)
        running = max(running, val)  # enforce monotonic non-decreasing
        adjusted[key] = running
    return adjusted


def descriptive(scores: list[CaseScore]) -> dict[str, int]:
    """Counts the report must carry (§17): cases, expected atoms, runs, failures."""
    cases = {s.case_id for s in scores}
    return {
        "n_cases": len(cases),
        "n_runs": len(scores),
        "n_scored": sum(1 for s in scores if s.scored),
        "n_failed": sum(1 for s in scores if not s.scored),
        "expected_atoms": sum(s.tp + s.fn for s in scores if s.scored and not s.expected_noop),
    }
