# Loop Contracts

The loop contracts live in `services/api/app/loops/types.py`.

## LoopDefinition

```text
id
name
purpose
trigger
input_contract
output_contract
states
policy_gates
audit_events
failure_modes
fallback_behavior
evidence_required
```

`LoopDefinition` is static architecture. It explains what a loop is allowed to do
and what evidence it must produce.

## LoopRun

```text
id
loop_id
trace_id
tenant_id
user_id
status
started_at
ended_at
metadata
```

`LoopRun` is one execution of a loop. Status is one of:

```text
running
completed
safe_degraded
failed
```

## LoopEvent

```text
id
loop_run_id
loop_id
trace_id
state_from
state_to
event_type
reason
evidence
audit_event_id
created_at
```

`LoopEvent` is one transition or evidence point within a run.

## Allowed States

```text
observed
classified
policy_checked
executed
verified
audited
feedback_captured
learned
safe_degraded
failed
completed
```

## Allowed Transitions

The source of truth is `ALLOWED_TRANSITIONS` in
`services/api/app/loops/state_machine.py`.

Key rules:

- A loop must start at `observed`.
- `classified` moves to `policy_checked`.
- `policy_checked` moves to `executed`, `safe_degraded`, or `failed`.
- `executed` moves to `verified`, `audited`, `safe_degraded`, or `failed`.
- `safe_degraded` is not failure; it moves to `audited` or `completed`.
- `audited` can complete, capture feedback, or record learning.

## Event Naming Rules

Use stable snake-case event names:

```text
<loop family>_<state/action>
```

Examples:

```text
memory_write_policy_checked
memory_read_safe_degraded
memory_governance_audited
continuous_learning_completed
```

## Metadata Safety Rules

Loop metadata is operational evidence, not a data lake.

- Do not store raw prompts, API keys, passwords, or full user messages.
- Prefer booleans, counts, IDs, statuses, and enum values.
- Truncate long strings.
- Redact secret-like patterns before persistence.
- Link to audit events by ID instead of duplicating audit payloads.
