"""Registry of MemoryOps loop definitions (v0.2.2)."""

from __future__ import annotations

from .types import LoopDefinition, LoopId, LoopState

LOOP_REGISTRY: dict[LoopId, LoopDefinition] = {
    LoopId.MEMORY_WRITE: LoopDefinition(
        id=LoopId.MEMORY_WRITE,
        name="Memory Write Loop",
        purpose="Decide whether user-provided information should become memory.",
        trigger="User sends a message or explicit remember instruction.",
        input_contract="ChatRequest message plus tenant/user/session settings.",
        output_contract="Policy decisions, optional stored memory IDs, and audit evidence.",
        states=[
            LoopState.OBSERVED,
            LoopState.CLASSIFIED,
            LoopState.POLICY_CHECKED,
            LoopState.EXECUTED,
            LoopState.VERIFIED,
            LoopState.AUDITED,
            LoopState.COMPLETED,
        ],
        policy_gates=[
            "PII/secret scan",
            "sensitivity classification",
            "utility evaluation",
            "tenant/user scope validation",
            "temporary chat check",
        ],
        audit_events=[
            "memory_created",
            "memory_pending_approval",
            "memory_blocked",
            "memory_dropped",
            "memory_updated",
            "memory_merged",
        ],
        failure_modes=[
            "memory pollution",
            "unsafe memory storage",
            "secret stored as memory",
            "wrong tenant attribution",
            "extractor hallucination",
            "duplicate/conflicting memory",
        ],
        fallback_behavior=[
            "drop low-utility candidate",
            "block unsafe candidate",
            "mark medium/high sensitivity as pending approval",
            "continue chat without saving memory",
            "audit decision",
        ],
        evidence_required=[
            "policy decision",
            "source/provenance",
            "audit event",
            "test or eval coverage",
        ],
    ),
    LoopId.MEMORY_READ: LoopDefinition(
        id=LoopId.MEMORY_READ,
        name="Memory Read Loop",
        purpose="Retrieve only relevant, allowed, active memories for a response.",
        trigger="User sends a message and memory is enabled.",
        input_contract="Tenant/user-scoped query plus memory settings.",
        output_contract="Used memories, score breakdowns, retrieval mode, and audit evidence.",
        states=[
            LoopState.OBSERVED,
            LoopState.POLICY_CHECKED,
            LoopState.EXECUTED,
            LoopState.VERIFIED,
            LoopState.AUDITED,
            LoopState.COMPLETED,
            LoopState.SAFE_DEGRADED,
        ],
        policy_gates=[
            "tenant filter",
            "user filter",
            "status = active",
            "deleted_at is null",
            "temporary chat is false",
            "sensitivity allowed",
        ],
        audit_events=["memory_retrieved", "retrieval_fallback", "context_compression_failed"],
        failure_modes=[
            "wrong memory retrieved",
            "deleted memory retrieved",
            "cross-tenant leakage",
            "irrelevant memory injected",
            "retrieval timeout",
            "compression failure",
        ],
        fallback_behavior=[
            "respond without memory",
            "fall back from vector to keyword retrieval",
            "fall back from compressed to uncompressed context",
            "audit retrieval failure",
        ],
        evidence_required=[
            "retrieved memory IDs",
            "score breakdown",
            "audit event",
            "eval result",
        ],
    ),
    LoopId.MEMORY_GOVERNANCE: LoopDefinition(
        id=LoopId.MEMORY_GOVERNANCE,
        name="Memory Governance Loop",
        purpose="Allow user/admin control over remembered information.",
        trigger="User or admin views, edits, approves, archives, rejects, or deletes memory.",
        input_contract="Scoped memory action with actor tenant/user and target memory ID.",
        output_contract="Memory status/content transition and append-only audit evidence.",
        states=[
            LoopState.OBSERVED,
            LoopState.POLICY_CHECKED,
            LoopState.EXECUTED,
            LoopState.VERIFIED,
            LoopState.AUDITED,
            LoopState.COMPLETED,
        ],
        policy_gates=[
            "user owns memory",
            "admin has tenant scope",
            "delete request is irreversible or soft-delete marked",
            "pending memory requires approval",
        ],
        audit_events=[
            "memory_viewed",
            "memory_updated",
            "memory_approved",
            "memory_rejected",
            "memory_archived",
            "memory_deleted",
        ],
        failure_modes=[
            "deleted memory still retrievable",
            "admin changes memory without audit",
            "source/provenance lost",
            "approval bypassed",
        ],
        fallback_behavior=[
            "block unauthorized action",
            "audit denied action",
            "preserve original source",
            "require explicit confirmation for delete",
        ],
        evidence_required=[
            "audit event",
            "state transition",
            "actor identity",
            "memory status update",
        ],
    ),
    LoopId.MEMORY_EVALUATION: LoopDefinition(
        id=LoopId.MEMORY_EVALUATION,
        name="Memory Evaluation Loop",
        purpose="Measure whether memory capture, retrieval, and governance are working.",
        trigger="Eval command, CI run, PR gate, or release validation.",
        input_contract="Golden/adversarial eval cases and critical invariant set.",
        output_contract="Pass/fail report, critical invariant status, and validation evidence.",
        states=[
            LoopState.OBSERVED,
            LoopState.EXECUTED,
            LoopState.VERIFIED,
            LoopState.AUDITED,
            LoopState.COMPLETED,
            LoopState.FAILED,
        ],
        policy_gates=[
            "critical invariants must pass",
            "eval cases must cover changed surfaces",
            "regressions must block release",
        ],
        audit_events=["eval_run_completed", "eval_run_failed"],
        failure_modes=[
            "eval drift",
            "missing adversarial case",
            "false confidence from manual testing",
            "release without invariant evidence",
        ],
        fallback_behavior=[
            "block PR",
            "block release",
            "add missing eval",
            "document limitation",
        ],
        evidence_required=[
            "eval result",
            "test result",
            "PR gate result",
            "validation command output",
        ],
    ),
    LoopId.RELEASE_GATE: LoopDefinition(
        id=LoopId.RELEASE_GATE,
        name="Release Gate Loop",
        purpose="Ensure every version is tagged only after validation evidence exists.",
        trigger="Preparing v0.x release.",
        input_contract="Candidate commit hash, release notes, and validation outputs.",
        output_contract="Release decision with tag target and known limitations.",
        states=[
            LoopState.OBSERVED,
            LoopState.EXECUTED,
            LoopState.VERIFIED,
            LoopState.AUDITED,
            LoopState.COMPLETED,
            LoopState.FAILED,
        ],
        policy_gates=[
            "tests pass",
            "evals pass",
            "lint/build pass or documented environment limitation",
            "release notes prepared",
            "known limitations documented",
            "tag points to correct commit",
        ],
        audit_events=["release_gate_checked"],
        failure_modes=[
            "tag wrong commit",
            "release notes missing",
            "dirty working tree",
            "tests not rerun",
            "AI co-author trailer accidentally added",
        ],
        fallback_behavior=[
            "stop release",
            "fix dirty tree",
            "retag only if not pushed",
            "document validation caveat",
        ],
        evidence_required=[
            "git hash",
            "test results",
            "eval results",
            "release title",
            "manual release notes",
        ],
    ),
    LoopId.LEARNING_CONTINUOUS: LoopDefinition(
        id=LoopId.LEARNING_CONTINUOUS,
        name="Continuous Learning Loop",
        purpose=(
            "Improve memory quality through feedback, decay, conflict handling, "
            "and reflection."
        ),
        trigger=(
            "User feedback, memory correction, eval failure, stale memory, "
            "conflict detection, worker run."
        ),
        input_contract="Feedback or worker signal plus scoped memory target.",
        output_contract="Review/archive/learn decision with audit evidence.",
        states=[
            LoopState.OBSERVED,
            LoopState.CLASSIFIED,
            LoopState.EXECUTED,
            LoopState.VERIFIED,
            LoopState.AUDITED,
            LoopState.LEARNED,
            LoopState.COMPLETED,
        ],
        policy_gates=[
            "feedback source is valid",
            "memory owner matches",
            "reflection does not create unsafe memory",
            "decay does not delete protected memory",
        ],
        audit_events=["memory_feedback_recorded", "memory_archived", "worker_learning_event"],
        failure_modes=[
            "bad feedback poisons memory",
            "stale memory remains active",
            "conflicting memory not resolved",
            "reflection creates false memory",
        ],
        fallback_behavior=[
            "mark for review",
            "archive instead of delete",
            "require approval for reflection-generated memory",
            "audit all changes",
        ],
        evidence_required=[
            "feedback event",
            "worker event",
            "memory status transition",
            "audit event",
        ],
    ),
}


def list_loop_definitions() -> list[LoopDefinition]:
    return list(LOOP_REGISTRY.values())


def get_loop_definition(loop_id: LoopId | str) -> LoopDefinition | None:
    try:
        key = loop_id if isinstance(loop_id, LoopId) else LoopId(loop_id)
    except ValueError:
        return None
    return LOOP_REGISTRY.get(key)
