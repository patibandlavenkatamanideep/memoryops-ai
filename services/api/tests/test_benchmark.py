"""Public memory-governance benchmark (v2.2).

Proves the benchmark runner categorizes the eval suite into public scorecards, that the
critical suites (deletion/leakage + tenant isolation) are perfect, and that every eval
case kind maps to a suite (nothing silently uncategorized).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BENCH = _REPO_ROOT / "benchmark"
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))

import run_benchmark  # noqa: E402


def test_scorecard_has_all_suites_and_overall():
    card = run_benchmark.score()
    assert set(card["suites"]) == set(run_benchmark.SUITES)
    assert card["overall"]["total"] > 0
    assert 0.0 <= card["overall"]["pass_rate"] <= 1.0


def test_critical_suites_are_perfect():
    card = run_benchmark.score()
    assert card["critical_suites_perfect"] is True
    for name in run_benchmark.CRITICAL:
        suite = card["suites"][name]
        assert suite["total"] > 0 and suite["passed"] == suite["total"]


def test_every_eval_kind_is_categorized():
    # No eval case kind should fall outside the published suites.
    card = run_benchmark.score()
    assert card["uncategorized_kinds"] == []


def test_deletion_and_leakage_suite_covers_the_leakage_family():
    card = run_benchmark.score()
    kinds = {c["kind"] for c in card["suites"]["deletion_and_leakage"]["cases"]}
    assert {"leakage", "cross_session_leakage", "expiry_leakage", "derived_tombstone"} <= kinds


def test_markdown_leaderboard_renders():
    md = run_benchmark._leaderboard_md(run_benchmark.score())
    assert "memory-governance scorecard" in md
    assert "deletion_and_leakage" in md and "|" in md
