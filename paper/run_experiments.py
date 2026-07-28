"""Run the deterministic invariant cases across all systems and print a scorecard.

Phase 2/3 entry point (protocol §10). Deliberately offline + reproducible: uses the
stub LLM + embeddings, so it needs no keys and no infra. Model-dependent quality
(H2 answer correctness) is out of scope here — these are the model-independent
invariant families (isolation, deletion leakage).

    python paper/run_experiments.py            # print the scorecard
    python paper/run_experiments.py --json      # machine-readable results + manifest

External systems (S4 Mem0) are included only when importable; otherwise skipped so
the run stays reproducible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root

from paper.harness import baselines as bl  # noqa: E402
from paper.harness import memoryops_adapter as moa  # noqa: E402
from paper.harness.cases import default_cases  # noqa: E402
from paper.harness.runner import build_manifest, run_suite, scorecard  # noqa: E402


def _factories():
    fac = [moa.s0, moa.s0u, bl.s1, bl.s2, bl.s3]
    try:  # S4 Mem0 is optional; include only if the adapter + package are present.
        from paper.harness import mem0_adapter

        if mem0_adapter.available():
            fac.append(mem0_adapter.s4)
    except Exception:  # noqa: BLE001 — stay reproducible without Mem0
        pass
    return fac


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Governance-runtime study — invariant cases")
    ap.add_argument("--json", action="store_true", help="emit JSON results + manifests")
    args = ap.parse_args(argv)

    cases = default_cases()
    factories = _factories()
    results = run_suite(factories, cases)

    if args.json:
        payload = {
            "manifests": [build_manifest(f().name).to_dict() for f in factories],
            "cases": [c.id for c in cases],
            "results": [
                {"system": r.system, "case": r.case_id, "suite": r.suite,
                 "outcome": r.outcome.value, "detail": r.detail}
                for r in results
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(f"Systems: {[f().name for f in factories]}")
        print(f"Cases: {len(cases)}  (suites: {sorted({c.suite for c in cases})})\n")
        print(scorecard(results))
        print("\nLegend: pass/fail are graded; unsupported = capability absent "
              "(reported separately, not a failure); error = crash/timeout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
