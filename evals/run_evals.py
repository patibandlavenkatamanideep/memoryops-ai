#!/usr/bin/env python3
"""Standalone eval runner for MemoryOps AI.

Builds an isolated in-memory stack and runs the golden + adversarial cases.
Pass criteria (exit 0):
  - all invariant cases pass (block/deleted/isolation/temporary/pending)
  - overall pass rate >= 0.80

Usage:
  python evals/run_evals.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the API package importable without installing it.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from app.services.eval_harness import run_evals  # noqa: E402

# Invariant cases that must NEVER fail, regardless of overall rate. The deletion /
# leakage kinds (v1.4–v1.5) prove the core guarantee — deleted or expired memory can
# never influence output — so they gate releases too.
_CRITICAL_KINDS = {
    "block", "deleted", "isolation", "temporary", "archived",
    "leakage", "derived_tombstone", "cross_session_leakage", "expiry_leakage",
}


def main() -> int:
    report = run_evals()
    print(f"\nMemoryOps AI — eval report ({report.passed}/{report.total} passed, "
          f"rate={report.pass_rate:.0%})\n")
    critical_failed = False
    for r in report.results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"  [{mark}] {r.id:32s} ({r.kind:10s}) {r.detail}")
        if not r.passed and r.kind in _CRITICAL_KINDS:
            critical_failed = True

    print()
    print(f"Loop evidence: {report.to_dict()['loop_engineering']}")
    print()
    if critical_failed:
        print("RESULT: FAIL — a critical invariant case did not pass.")
        return 1
    if report.pass_rate < 0.80:
        print(f"RESULT: FAIL — pass rate {report.pass_rate:.0%} below 80% threshold.")
        return 1
    print("RESULT: PASS — all invariants hold and pass rate >= 80%.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
