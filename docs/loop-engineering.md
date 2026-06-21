# Loop Engineering

MemoryOps AI models memory as a governed loop-engineered system, not a passive
store. The operating model is:

```text
Observe -> Decide -> Act -> Verify -> Audit -> Learn
```

Memory is produced by loops, retrieved by loops, corrected by loops, forgotten by
loops, and improved by loops. The loop layer makes those workflows visible,
testable, auditable, and governable.

## Why MemoryOps Uses Loops

Memory failures are usually process failures: unsafe content is saved, stale
content is retrieved, deletion is not verified, or releases ship without evidence.
Loop engineering turns each process into an explicit contract with states, policy
gates, failure modes, fallback behavior, and evidence requirements.

## Six Primary Loops

| Loop | Purpose |
|---|---|
| `memory.write` | Decide whether user-provided information should become memory. |
| `memory.read` | Retrieve only relevant, allowed, active memories for a response. |
| `memory.governance` | Let users/admins view, edit, approve, archive, reject, or delete memory. |
| `memory.evaluation` | Measure capture, retrieval, governance, and invariant behavior. |
| `release.gate` | Ensure a version is tagged only after validation evidence exists. |
| `learning.continuous` | Improve memory quality through feedback, decay, conflict handling, and reflection. |

## State Transitions

The shared state vocabulary is defined in `services/api/app/loops/types.py`.
Allowed transitions are enforced by `services/api/app/loops/state_machine.py`.
Invalid transitions raise an exception and are covered by tests.

Common path:

```text
observed -> classified -> policy_checked -> executed -> verified -> audited -> completed
```

Safe degradation path:

```text
policy_checked/executed -> safe_degraded -> audited -> completed
```

Failure path:

```text
observed/classified/policy_checked/executed/verified -> failed -> audited
```

## Policy Gates

Each loop declares the gates that must hold before it can be trusted. Examples:

- `memory.write`: secret scan, sensitivity classification, utility evaluation,
  tenant/user scope validation, temporary-chat check.
- `memory.read`: tenant filter, user filter, active status, deleted exclusion,
  temporary-chat exclusion.
- `release.gate`: tests/evals/build evidence, release notes, correct tag target,
  known limitation disclosure.

## Audit Events

Loop events and audit events answer different questions:

- Loop events: "Where is this workflow in the decision loop?"
- Audit events: "Who did what, when, and why?"

Loop events can link to audit events through `audit_event_id`, but they do not
duplicate the audit log. They are operational traces.

## Failure Modes And Fallbacks

Each loop declares known failures and safe fallbacks. Examples:

- Wrong/deleted/cross-tenant memory retrieval falls back to no memory or
  keyword-only retrieval and records safe degradation.
- Unsafe memory write decisions block or pend the candidate while chat continues.
- Release validation caveats must be documented before tagging.

## Preventing Memory Failures

Loop engineering prevents memory failures by making every important workflow
observable and testable. A memory write is not complete just because a row was
inserted; it must pass policy, verify storage or blocking behavior, and link audit
evidence. A read is not complete just because retrieval returned text; it must
prove tenant/user/status filters and explain which memory was used.

## Fit With agentic-swe-kit

The loop layer maps naturally to agentic-swe-kit phase gates:

- workflow orchestration: loop definitions and transitions
- memory architecture: read/write loop contracts
- evaluation systems: eval evidence and loop summaries
- observability: loop run/event traces
- CI/CD for AI: release gate and PR invariant evidence rules
- continuous learning: worker loop evidence for decay/archive/conflict/reflection

## Fit With Release Discipline

`release.gate` is the release checklist as a loop. It does not tag automatically.
It records the policy gates a human must satisfy before running the tag command:
tests, evals, lint/build or documented caveats, release notes, and the exact
commit hash.
