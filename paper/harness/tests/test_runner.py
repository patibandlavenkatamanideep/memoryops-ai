"""End-to-end: the runner over the deterministic case set across all five systems.

This is the study's first cross-system comparison. It asserts the *shape* of the
result that the protocol predicts (H1 capability coverage), not tuned numbers:
- every system isolates by scope (no cross-tenant/user leak);
- systems that cannot forget (S1 full-context, S3 summary) are `unsupported` on the
  deletion cases — a coverage finding, not a failure;
- systems that can forget (S0, S0-U, S2) pass the deletion cases (no resurfacing).
"""

from __future__ import annotations

import pytest

bl = pytest.importorskip("paper.harness.baselines")  # installs the bridge
pytest.importorskip("app.embeddings")
from paper.harness import memoryops_adapter as moa  # noqa: E402
from paper.harness.cases import default_cases  # noqa: E402
from paper.harness.runner import build_manifest, run_case, run_suite, scorecard, tally  # noqa: E402
from paper.harness.types import Outcome  # noqa: E402

FACTORIES = [moa.s0, moa.s0u, bl.s1, bl.s2, bl.s3]
CASES = default_cases()


def _by_system(results):
    out = {}
    for r in results:
        out.setdefault(r.system, {})[r.case_id] = r
    return out


@pytest.fixture(scope="module")
def results():
    return run_suite(FACTORIES, CASES)


def test_no_system_leaks_across_scope(results):
    # Isolation cases must not FAIL for any system.
    for r in results:
        if r.suite == "tenant_isolation":
            assert r.outcome is not Outcome.FAIL, f"{r.system} leaked on {r.case_id}"


def test_forgetful_systems_pass_deletion(results):
    by = _by_system(results)
    for sysname in ("S0", "S0-U", "S2"):
        for cid in ("del-exact-probe", "del-paraphrased-probe"):
            assert by[sysname][cid].outcome is Outcome.PASS, (sysname, cid)


def test_non_forgetful_systems_report_unsupported_not_fail(results):
    by = _by_system(results)
    for sysname in ("S1", "S3"):
        for cid in ("del-exact-probe", "del-paraphrased-probe"):
            assert by[sysname][cid].outcome is Outcome.UNSUPPORTED, (sysname, cid)


def test_no_errors_anywhere(results):
    errs = [r for r in results if r.outcome is Outcome.ERROR]
    assert not errs, f"unexpected errors: {[(r.system, r.case_id, r.detail) for r in errs]}"


def test_scorecard_and_tally_cover_all_systems(results):
    counts = tally(results)
    assert set(counts) == {"S0", "S0-U", "S1", "S2", "S3"}
    card = scorecard(results)
    for name in ("S0", "S0-U", "S1", "S2", "S3"):
        assert name in card


def test_single_case_run_smoke():
    r = run_case(bl.s2(), CASES[0])
    assert r.system == "S2" and r.outcome in set(Outcome)


def test_manifest_captures_provenance():
    m = build_manifest("S0")
    assert m.system == "S0" and m.benchmark_version and m.env.get("python")
