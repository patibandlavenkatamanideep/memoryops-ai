#!/usr/bin/env python3
"""MemoryOps AI — public memory-governance benchmark (v2.2).

Most memory projects *claim* governance. This benchmark *measures* it: it runs the
real eval harness (golden + adversarial + leakage cases) against an isolated,
offline stack and scores the results into named suites, so anyone can reproduce the
numbers and compare their own memory system on the same axes:

  * deletion_and_leakage — deleted/expired memory must not be retrieved or leak
    (directly, indirectly, cross-session, via summaries, or after reindex)
  * tenant_isolation     — no cross-tenant / cross-user retrieval
  * context_admission    — only relevant *and* allowed memory enters context;
    archived/temporary paths behave
  * policy_governance    — policy-before-storage: secrets/injection BLOCK,
    trivia DROP, sensitive PENDING, real preferences SAVE
  * retrieval_quality    — hybrid retrieval + explainable score breakdown

Usage:
  python benchmark/run_benchmark.py            # print scorecard + leaderboard
  python benchmark/run_benchmark.py --json     # machine-readable scorecard
  python benchmark/run_benchmark.py --md out.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "services" / "api"))

from app.services.eval_harness import run_evals  # noqa: E402

# Which eval case kinds roll up into each public suite.
SUITES: dict[str, set[str]] = {
    "deletion_and_leakage": {
        "deleted", "leakage", "cross_session_leakage", "expiry_leakage", "derived_tombstone",
    },
    "tenant_isolation": {"isolation"},
    "context_admission": {"archived", "temporary"},
    "policy_governance": {"save", "drop", "block", "pending", "structured", "conflict", "multi_memory"},
    "retrieval_quality": {"retrieve", "breakdown", "loop"},
}

# Suites that must be perfect — the core trust story.
CRITICAL = {"deletion_and_leakage", "tenant_isolation"}


def score() -> dict:
    report = run_evals()
    kind_to_suite = {k: suite for suite, kinds in SUITES.items() for k in kinds}
    suites: dict[str, dict] = {name: {"passed": 0, "total": 0, "cases": []} for name in SUITES}
    uncategorized: list[str] = []
    for r in report.results:
        suite = kind_to_suite.get(r.kind)
        if suite is None:
            uncategorized.append(r.kind)
            continue
        s = suites[suite]
        s["total"] += 1
        s["passed"] += 1 if r.passed else 0
        s["cases"].append({"id": r.id, "kind": r.kind, "passed": r.passed})
    for s in suites.values():
        s["pass_rate"] = round(s["passed"] / s["total"], 4) if s["total"] else None
    critical_ok = all(
        suites[name]["total"] > 0 and suites[name]["passed"] == suites[name]["total"]
        for name in CRITICAL
    )
    return {
        "benchmark": "memoryops-memory-governance",
        "version": "v2.2",
        "system": "MemoryOps AI",
        "overall": {
            "passed": report.passed,
            "total": report.total,
            "pass_rate": round(report.pass_rate, 4),
        },
        "suites": suites,
        "critical_suites_perfect": critical_ok,
        "uncategorized_kinds": sorted(set(uncategorized)),
    }


def _leaderboard_md(card: dict) -> str:
    lines = [
        f"# {card['system']} — memory-governance scorecard ({card['version']})",
        "",
        f"**Overall:** {card['overall']['passed']}/{card['overall']['total']} "
        f"({card['overall']['pass_rate']:.0%}) · "
        f"critical suites perfect: {'✅' if card['critical_suites_perfect'] else '❌'}",
        "",
        "| Suite | Pass rate | Passed / Total | Critical |",
        "| --- | --- | --- | --- |",
    ]
    for name, s in card["suites"].items():
        rate = "—" if s["pass_rate"] is None else f"{s['pass_rate']:.0%}"
        crit = "★" if name in CRITICAL else ""
        lines.append(f"| {name} | {rate} | {s['passed']} / {s['total']} | {crit} |")
    lines += [
        "",
        "> Reproduce: `python benchmark/run_benchmark.py`. Cases live in `evals/` and run",
        "> against an isolated, offline stub stack (no API keys). Bring your own memory",
        "> system and score it on the same suites.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="print machine-readable scorecard")
    ap.add_argument("--md", type=str, default=None, help="write the leaderboard markdown to a file")
    args = ap.parse_args()

    card = score()
    if args.json:
        print(json.dumps(card, indent=2))
    else:
        print(_leaderboard_md(card))
    if args.md:
        Path(args.md).write_text(_leaderboard_md(card))

    # Fail the benchmark if a critical suite is not perfect or overall < 80%.
    if not card["critical_suites_perfect"]:
        print("\nRESULT: FAIL — a critical suite (deletion/leakage or isolation) is not perfect.")
        return 1
    if card["overall"]["pass_rate"] < 0.80:
        print(f"\nRESULT: FAIL — overall {card['overall']['pass_rate']:.0%} below 80%.")
        return 1
    print("\nRESULT: PASS — critical suites perfect and overall ≥ 80%.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
