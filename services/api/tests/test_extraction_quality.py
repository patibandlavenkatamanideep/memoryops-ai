"""The extraction-quality runner works offline against the stub (P1.1).

This keeps the honest instrument runnable in CI without keys and guards the stub's
precision from regressing. Recall/multi-memory are intentionally *not* pinned high —
the whole point is that the stub trails real models there.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_RUNNER = Path(__file__).resolve().parents[3] / "evals" / "run_extraction_quality.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_extraction_quality", _RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stub_extraction_quality_is_scored():
    rq = _load_runner()
    cases = rq._load_cases()
    assert len(cases) >= 20
    score = rq.score_provider("stub", cases)
    # The stub should be precise (it rarely emits junk) and handle every no-op turn.
    assert score.precision >= 0.8
    assert score.noop_ok == score.noop_total
    # It extracts *some* memories and covers *some* facts — a real signal, not zero.
    assert score.extracted > 0 and score.covered > 0
    assert not score.errors


def test_fact_coverage_matcher():
    rq = _load_runner()
    assert rq._covers("boston", ["I live in Boston."])
    assert rq._covers("shellfish", ["I'm allergic to shellfish."])
    assert not rq._covers("peanut", ["I live in Boston."])


@pytest.mark.parametrize("provider", ["stub"])
def test_multi_memory_turns_beat_single(provider):
    rq = _load_runner()
    cases = [c for c in rq._load_cases() if len(c.get("expected_facts", [])) >= 2]
    score = rq.score_provider(provider, cases)
    # The stub must extract multiple memories on at least some compound turns.
    assert score.multi_ok >= 1
