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
    # ── v0.4 Provider LLM adapters + structured memory intelligence (ADR-008) ──
    Rule(
        "Memory Correctness",
        "llm-provider-tests",
        r"^services/api/app/llm/",
        r"^services/api/tests/test_(llm_|stub_llm_|structured_|conflict_).*\.py$",
        "LLM provider/intelligence code changed without LLM provider tests "
        "(test_llm_*/test_stub_llm_*/test_structured_*/test_conflict_*).",
    ),
    Rule(
        "Memory Correctness",
        "structured-schemas-tests",
        r"^services/api/app/llm/schemas\.py$",
        r"^services/api/tests/test_structured_output_validation\.py$",
        "Structured output schemas changed without structured-output validation tests.",
    ),
    Rule(
        "Memory Correctness",
        "llm-fallback-tests",
        r"^services/api/app/llm/(fallback|providers|registry|intelligence)\.py$",
        r"^services/api/tests/test_llm_fallback\.py$",
        "Provider fallback/orchestration changed without fallback tests.",
    ),
    Rule(
        "Memory Correctness",
        "extractor-extraction-eval",
        r"^services/api/app/services/extractor\.py$",
        r"^(evals/golden_memory_cases\.json$"
        r"|services/api/tests/test_structured_memory_extraction\.py$)",
        "Extractor changed without an extraction eval or structured-extraction test update.",
    ),
    Rule(
        "Docs/ADR",
        "llm-prompts-docs",
        r"^services/api/app/llm/prompts/",
        r"^(docs/(provider-llm-adapters|structured-memory-intelligence)\.md$|evals/)",
        "Prompt assets changed without updating provider/intelligence docs or evals.",
    ),
    Rule(
        "Docs/ADR",
        "llm-adapters-adr",
        r"^services/api/app/llm/",
        r"^(docs/provider-llm-adapters\.md$"
        r"|docs/structured-memory-intelligence\.md$"
        r"|infra/adr/ADR-008-provider-llm-adapters\.md$)",
        "LLM layer changed without updating provider/intelligence docs or ADR-008.",
    ),
    # ── v0.5 Governance UI + Memory Control Plane (ADR-009) ────────────────────
    Rule(
        "Memory Correctness",
        "governance-api-tests",
        r"^services/api/app/routes/memories\.py$",
        r"^services/api/tests/test_governance_api\.py$",
        "Memory governance API changed without governance API tests "
        "(tests/test_governance_api.py).",
    ),
    Rule(
        "Memory Correctness",
        "governance-ui-tests-or-docs",
        r"^apps/web/app/(memories|governance|audit)/",
        r"^(services/api/tests/test_governance_api\.py$"
        r"|docs/governance-ui\.md$|docs/memory-control-plane\.md$)",
        "Frontend governance page changed without a control-plane test or UI/control-plane "
        "doc update.",
    ),
    Rule(
        "Docs/ADR",
        "control-plane-adr",
        r"^apps/web/components/(memories|governance|audit)/|^services/api/app/routes/memories\.py$",
        r"^(docs/governance-ui\.md$|docs/memory-control-plane\.md$"
        r"|infra/adr/ADR-009-memory-control-plane\.md$)",
        "Memory control plane changed without updating governance-ui/memory-control-plane "
        "docs or ADR-009.",
    ),
    # ── v0.6 Background memory lifecycle workers (ADR-010) ─────────────────────
    Rule(
        "Memory Correctness",
        "worker-tests",
        r"^services/api/app/workers/",
        r"^services/api/tests/test_(lifecycle_worker|decay_worker|archive_worker"
        r"|deletion_verification_worker|deletion_compaction_worker|conflict_scan_worker"
        r"|worker_idempotency|worker_orchestrator|worker_locks|worker_retry"
        r"|worker_health)\.py$",
        "Background worker code changed without worker tests (tests/test_*_worker.py "
        "or test_worker_*.py).",
    ),
    Rule(
        "Security",
        "deletion-verification-tests",
        r"^services/api/app/workers/deletion_verification\.py$",
        r"^services/api/tests/test_deletion_verification_worker\.py$",
        "Deletion verification worker changed without deletion-verification worker tests.",
    ),
    Rule(
        "Security",
        "deletion-verification-docs",
        r"^services/api/app/workers/deletion_verification\.py$",
        r"^(docs/deletion-verification\.md$|docs/security\.md$)",
        "Deletion verification changed without updating deletion-verification or security docs.",
    ),
    Rule(
        "Docs/ADR",
        "decay-archive-docs",
        r"^services/api/app/workers/(decay|archive)\.py$",
        r"^(docs/memory-decay-policy\.md$|docs/background-lifecycle-workers\.md$)",
        "Decay/archive behavior changed without updating decay-policy or lifecycle-worker docs.",
    ),
    Rule(
        "Docs/ADR",
        "worker-audit-governance-docs",
        r"^services/api/app/workers/(lifecycle|schemas)\.py$",
        r"^(docs/background-lifecycle-workers\.md$|docs/governance\.md$"
        r"|docs/security\.md$|infra/adr/ADR-010-background-memory-lifecycle-workers\.md$)",
        "Worker audit/event behavior changed without updating lifecycle-worker, governance, "
        "or security docs / ADR-010.",
    ),
    Rule(
        "Docs/ADR",
        "worker-runner-evidence",
        r"^services/api/app/workers/runner\.py$",
        r"^(docs/phase-gates/phase-12-background-lifecycle-workers\.md$"
        r"|infra/adr/ADR-010-background-memory-lifecycle-workers\.md$"
        r"|docs/phase-gates/phase-13-deletion-compaction-vector-purge\.md$"
        r"|infra/adr/ADR-011-physical-deletion-compaction-vector-purge\.md$)",
        "Background worker runner changed without phase-gate or ADR evidence.",
    ),
    # ── v0.7 Physical deletion compaction + vector purge verification (ADR-011) ─
    Rule(
        "Security",
        "deletion-compaction-tests",
        r"^services/api/app/workers/deletion_compaction\.py$",
        r"^services/api/tests/test_deletion_compaction_worker\.py$",
        "Deletion compaction worker changed without deletion-compaction worker tests.",
    ),
    Rule(
        "Security",
        "vector-purge-verification-tests",
        r"^services/api/app/workers/vector_purge\.py$",
        r"^services/api/tests/test_vector_purge_verification\.py$",
        "Vector purge verification changed without vector-purge verification tests.",
    ),
    Rule(
        "Security",
        "compaction-repo-security-docs",
        r"^services/api/app/db/(repository|memory_repo|postgres_repo|entities)\.py$",
        r"^(docs/security\.md$|docs/governance\.md$|SECURITY\.md$)",
        "Repository deletion/compaction methods changed without updating security or "
        "governance docs.",
    ),
    Rule(
        "Security",
        "deletion-compaction-security-docs",
        r"^services/api/app/workers/deletion_compaction\.py$|^services/api/app/workers/vector_purge\.py$",
        r"^(docs/deletion-compaction\.md$|docs/vector-purge-verification\.md$"
        r"|docs/security\.md$|docs/deletion-verification\.md$)",
        "Deletion compaction / vector purge changed without updating deletion/security docs.",
    ),
    Rule(
        "Docs/ADR",
        "deletion-compaction-adr",
        r"^services/api/app/workers/deletion_compaction\.py$|^services/api/app/workers/vector_purge\.py$",
        r"^(infra/adr/ADR-011-physical-deletion-compaction-vector-purge\.md$"
        r"|docs/phase-gates/phase-13-deletion-compaction-vector-purge\.md$)",
        "Physical deletion compaction semantics changed without ADR-011 or phase-13 gate "
        "evidence.",
    ),
    Rule(
        "Docs/ADR",
        "compaction-audit-governance-docs",
        r"^services/api/app/workers/schemas\.py$",
        r"^(docs/background-lifecycle-workers\.md$|docs/governance\.md$"
        r"|docs/deletion-compaction\.md$|docs/security\.md$"
        r"|infra/adr/ADR-010-background-memory-lifecycle-workers\.md$"
        r"|infra/adr/ADR-011-physical-deletion-compaction-vector-purge\.md$)",
        "Worker audit/event schema changed without updating lifecycle/governance/security "
        "or deletion-compaction docs / an ADR.",
    ),
    # ── v0.8 Worker runtime + scheduled lifecycle orchestration (ADR-012) ───────
    Rule(
        "Reliability",
        "worker-runtime-tests",
        r"^services/api/app/workers/(orchestrator|scheduler|locks|retry)\.py$",
        r"^services/api/tests/test_worker_(orchestrator|locks|retry|health)\.py$",
        "Worker runtime (orchestrator/scheduler/locks/retry) changed without runtime tests "
        "(test_worker_orchestrator/locks/retry/health).",
    ),
    Rule(
        "Reliability",
        "worker-lease-isolation-tests",
        r"^services/api/app/workers/(orchestrator|locks)\.py$",
        r"^services/api/tests/test_worker_locks\.py$",
        "Lease / duplicate-run prevention changed without lock tests (test_worker_locks).",
    ),
    Rule(
        "Reliability",
        "worker-runtime-persistence-tests",
        r"^services/api/app/db/(repository|memory_repo|postgres_repo|entities)\.py$",
        r"^services/api/tests/test_worker_(orchestrator|locks|health)\.py$"
        r"|^services/api/tests/test_tenant_isolation\.py$",
        "Worker lease / run-history persistence changed without runtime or tenant-isolation "
        "tests.",
    ),
    Rule(
        "Docs/ADR",
        "worker-runtime-docs",
        r"^services/api/app/workers/(orchestrator|scheduler|locks|retry)\.py$|^services/worker/",
        r"^(docs/worker-runtime\.md$|docs/background-lifecycle-workers\.md$"
        r"|docs/deployment/railway\.md$"
        r"|infra/adr/ADR-012-worker-runtime-orchestration\.md$"
        r"|docs/phase-gates/phase-14-worker-runtime-orchestration\.md$)",
        "Worker runtime / worker process changed without updating worker-runtime, "
        "lifecycle-worker, or deployment docs / ADR-012 / phase-14 gate.",
    ),
    Rule(
        "Docs/ADR",
        "worker-runtime-adr",
        r"^services/api/app/workers/(orchestrator|scheduler)\.py$",
        r"^(infra/adr/ADR-012-worker-runtime-orchestration\.md$"
        r"|docs/phase-gates/phase-14-worker-runtime-orchestration\.md$)",
        "Worker orchestration/scheduling semantics changed without ADR-012 or phase-14 "
        "gate evidence.",
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
