#!/usr/bin/env python3
"""PR Invariant Evidence Gate (deterministic, no LLM).

Inspired by the ai-pr-review-agent architecture (security / memory-correctness /
evaluation / docs reviewers), reimplemented as a repo-local rule engine. It reads
the changed files between two git refs and fails when a sensitive surface changes
without matching evidence (tests / evals / docs / ADRs).

Usage:
    python scripts/pr_invariant_gate.py --base origin/main --head HEAD
    python scripts/pr_invariant_gate.py --base HEAD~1 --head HEAD
    python scripts/pr_invariant_gate.py --files a.py b.py   # explicit file list

Exit code 0 = all required evidence present (or no sensitive change).
Exit code 1 = at least one rule violated.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    reviewer: str
    name: str
    trigger: str          # regex: a changed file that arms the rule
    evidence: str         # regex: a changed file that satisfies it
    message: str          # shown when violated


# Reviewer domains mapped to MemoryOps file surfaces. Paths are real.
RULES: list[Rule] = [
    Rule(
        "Memory Correctness",
        "memory-lifecycle-tests",
        r"^services/api/app/services/(extractor|write_service|gateway)\.py$",
        r"^(services/api/tests/|evals/golden_memory_cases\.json$)",
        "Memory lifecycle code changed without a test or golden-eval update.",
    ),
    Rule(
        "Memory Correctness",
        "policy-adversarial",
        r"^services/api/app/services/policy_broker\.py$|^services/api/app/core/redaction\.py$",
        r"^(evals/adversarial_cases\.json$|services/api/tests/test_policy_broker\.py$)",
        "Policy broker / redaction changed without an adversarial-eval or policy-test update.",
    ),
    Rule(
        "Memory Correctness",
        "retrieval-eval",
        r"^services/api/app/services/(retriever|ranker|context_composer)\.py$",
        r"^(services/api/tests/test_(retrieval|hybrid_retrieval|retrieval_degradation)\.py$"
        r"|evals/)",
        "Retrieval/ranking changed without a retrieval-test or eval update.",
    ),
    Rule(
        "Memory Correctness",
        "embeddings-tests",
        r"^services/api/app/embeddings/|^services/api/app/core/embeddings\.py$",
        r"^services/api/tests/test_embeddings\.py$",
        "Embedding provider changed without updating tests/test_embeddings.py.",
    ),
    Rule(
        "Memory Correctness",
        "score-formula-docs",
        r"^services/api/app/services/ranker\.py$",
        r"^(docs/api-contracts\.md$|docs/architecture\.md$)",
        "Ranking/score formula changed without updating docs/api-contracts.md or "
        "docs/architecture.md.",
    ),
    Rule(
        "Security",
        "rls-migration-test",
        r"^infra/db/migrations/.*rls.*\.sql$",
        r"^services/api/tests/test_rls\.py$",
        "RLS migration changed without updating tests/test_rls.py.",
    ),
    Rule(
        "Security",
        "rls-migration-docs",
        r"^infra/db/migrations/.*rls.*\.sql$",
        r"^docs/security\.md$",
        "RLS migration changed without updating docs/security.md.",
    ),
    Rule(
        "Memory Correctness",
        "compression-tests",
        r"^services/api/app/compression/",
        r"^services/api/tests/test_(context_compression|compression_invariants|headroom_fallback)\.py$",
        "Compression code changed without a compression-behavior or invariant test.",
    ),
    Rule(
        "Memory Correctness",
        "loop-tests",
        r"^services/api/app/loops/",
        r"^services/api/tests/test_loop_.*\.py$",
        "Loop engineering code changed without test_loop_* coverage.",
    ),
    Rule(
        "Memory Correctness",
        "loop-state-machine-tests",
        r"^services/api/app/loops/state_machine\.py$",
        r"^services/api/tests/test_loop_state_machine\.py$",
        "Loop state machine changed without transition tests.",
    ),
    Rule(
        "Memory Correctness",
        "loop-doc-contract",
        r"^docs/loop-engineering\.md$",
        r"^(docs/loop-contracts\.md$|services/api/tests/test_loop_registry\.py$)",
        "Loop engineering docs changed without loop contracts or registry tests.",
    ),
    Rule(
        "Memory Correctness",
        "memory-path-loop-evidence",
        r"^services/api/app/services/gateway\.py$|^services/api/app/services/(retriever|ranker|context_composer|write_service|extractor|policy_broker)\.py$",
        r"^(services/api/tests/test_(loop_|memory_write_loop|memory_read_loop).*\.py$|evals/)",
        "Memory write/read path changed without loop-event tests or eval evidence.",
    ),
    Rule(
        "Docs/ADR",
        "release-loop-docs",
        r"^(docs/release-loop\.md$|RELEASING\.md$)",
        r"^(docs/release-loop\.md$|RELEASING\.md$)",
        "Release docs changed without the release loop contract.",
    ),
    Rule(
        "Memory Correctness",
        "composer-compression",
        r"^services/api/app/services/context_composer\.py$",
        r"^(services/api/tests/test_(compression_invariants|retrieval)\.py$|evals/)",
        "Context composer changed without a compression-invariant or retrieval test/eval.",
    ),
    Rule(
        "Docs/ADR",
        "compression-economics-docs",
        r"^services/api/app/compression/|^services/api/app/services/gateway\.py$",
        r"^(docs/token-compression\.md$|docs/phase-gates/phase-16-economics\.md$"
        r"|docs/integrations/headroom\.md$|infra/adr/ADR-007-headroom-token-compression\.md$"
        r"|services/api/tests/)",
        "Compression/cost path changed without updating token-compression/economics docs "
        "or a test.",
    ),
    Rule(
        "Security",
        "deletion-invariant",
        r"^services/api/app/db/|^services/api/app/routes/memories\.py$",
        r"^services/api/tests/test_deletion\.py$",
        "Deletion/repository logic changed without a deleted-memory invariant test.",
    ),
    Rule(
        "Security",
        "tenant-isolation",
        r"^services/api/app/db/",
        r"^services/api/tests/test_tenant_isolation\.py$",
        "Tenant/user filtering changed without a cross-tenant leakage test.",
    ),
    Rule(
        "Security",
        "security-docs",
        r"^services/api/app/core/redaction\.py$|^services/api/app/db/",
        r"^(SECURITY\.md$|docs/security\.md$)",
        "Security-sensitive code changed without updating SECURITY.md or docs/security.md.",
    ),
    Rule(
        "Docs/ADR",
        "migrations-docs",
        r"^infra/db/",
        r"^(docs/architecture\.md$|infra/adr/)",
        "Migrations changed without updating docs/architecture.md or an ADR.",
    ),
    Rule(
        "Docs/ADR",
        "api-contracts",
        r"^services/api/app/routes/",
        r"^(docs/api-contracts\.md$|docs/architecture\.md$)",
        "API routes changed without updating docs/api-contracts.md or docs/architecture.md.",
    ),
]


def changed_files(base: str | None, head: str, explicit: list[str] | None) -> list[str]:
    if explicit:
        return explicit
    ref = f"{base}...{head}" if base else head
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", ref], text=True, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        # Fall back to a two-dot diff if the three-dot merge-base form fails.
        out = subprocess.check_output(
            ["git", "diff", "--name-only", f"{base}..{head}" if base else head], text=True
        )
    return [line.strip() for line in out.splitlines() if line.strip()]


def evaluate(files: list[str]) -> tuple[list[Rule], list[Rule]]:
    """Return (violations, satisfied) for rules whose trigger matched."""
    violations: list[Rule] = []
    satisfied: list[Rule] = []
    for rule in RULES:
        trigger = re.compile(rule.trigger)
        if not any(trigger.search(f) for f in files):
            continue  # rule not armed
        evidence = re.compile(rule.evidence)
        if any(evidence.search(f) for f in files):
            satisfied.append(rule)
        else:
            violations.append(rule)
    return violations, satisfied


def main() -> int:
    ap = argparse.ArgumentParser(description="MemoryOps PR Invariant Evidence Gate")
    ap.add_argument("--base", default=None, help="base ref (e.g. origin/main, HEAD~1)")
    ap.add_argument("--head", default="HEAD", help="head ref (default HEAD)")
    ap.add_argument("--files", nargs="*", help="explicit file list (skips git diff)")
    args = ap.parse_args()

    files = changed_files(args.base, args.head, args.files)
    print("MemoryOps AI — PR Invariant Evidence Gate")
    print(f"Comparing: base={args.base or '(none)'} head={args.head}")
    print(f"Changed files: {len(files)}")
    for f in files:
        print(f"  - {f}")
    print()

    violations, satisfied = evaluate(files)

    for r in satisfied:
        print(f"[OK]   {r.reviewer:18s} {r.name}: evidence present")
    for r in violations:
        print(f"[FAIL] {r.reviewer:18s} {r.name}: {r.message}")

    print()
    if violations:
        print(f"RESULT: FAIL — {len(violations)} rule(s) need evidence "
              "(tests / evals / docs / ADRs).")
        return 1
    armed = len(satisfied)
    print(f"RESULT: PASS — {armed} armed rule(s) satisfied; no sensitive change unguarded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
