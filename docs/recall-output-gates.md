# Recall Gate + Output Gate

Governance has two edges around the model, not one. The
[Context Admission Gate](context-admission-gate.md) decides what memory *enters* the
prompt. v1.9 ([ADR-023](../infra/adr/ADR-023-recall-output-gates.md)) adds the missing
audience dimension on the way in — the **Recall Gate** — and a second control on the
way out — the **Output Gate**.

```
retrieve → rank → admission → RECALL → compose → LLM → OUTPUT GATE → answer
                              (v1.9)                     (v1.9)
```

Both are **on by default but no-op** unless there is something to protect: the default
`private` audience clears every sensitivity, and an honest model discloses nothing, so
existing behavior is unchanged.

## Recall Gate — audience-aware entry

Admission answers "is this memory allowed at all?" (deleted / expired / consent /
tombstone / relevance). The Recall Gate answers "should it be recalled for **this**
session?" A memory that is perfectly admissible for a private session must not be
recalled into a shared or public one.

Each request carries an `audience`; a memory is recalled only if its `sensitivity` is
within that audience's clearance:

| `audience` | recalls sensitivities |
| --- | --- |
| `private` (default) | low + medium + high |
| `team` | low + medium |
| `public` | low only |

A memory the gate withholds shows up in the [Memory Usage Trace](context-admission-gate.md)
as `memories_blocked` with decision **`BLOCK_AUDIENCE`** — same trace, metrics, and
audit machinery as every other block. The gate only ever *removes* memory
(defense-in-depth; tenant isolation and the deletion guarantee are untouched).

```jsonc
// POST /api/chat  { …, "audience": "public" }
// a high-sensitivity memory is blocked from context:
"trace": { "memories_blocked": [
  { "memory_id": "…", "sensitivity": "high",
    "admission_decision": "BLOCK_AUDIENCE",
    "admission_reason": "sensitivity 'high' exceeds 'public' audience clearance" }
]}
```

## Output Gate — disclosure control after generation

The pre-composition gates can't see what the model *says*. A real LLM can ignore
instructions and echo withheld context, be coaxed by prompt injection, or infer and
restate blocked material. The Output Gate inspects the generated answer and catches
content that would disclose a memory the Recall/Admission gates blocked.

It is **deterministic and no-throw**: it flags a disclosure when the answer shares a
distinctive contiguous phrase (≥ 4 significant words) with a *protected* (blocked)
memory, then:

- `redact` (default) — replaces the offending spans with `[redacted]`;
- `refuse` — returns a safe refusal message instead of the answer.

Either way it sets an escalation flag, appends an `output_gate_blocked` audit event,
and surfaces an `output_gate` block on the response. On any internal error it returns
the original answer unchanged — the gate never fails a request.

```jsonc
// when the model would have leaked a blocked memory:
"output_gate": { "action": "redacted", "disclosures": 1, "escalated": true }
```

## Toggles

| Env | Default | Effect |
| --- | --- | --- |
| `MEMORYOPS_RECALL_GATE` | `true` | audience-aware recall (no-op for `private`) |
| `MEMORYOPS_OUTPUT_GATE` | `true` | post-generation disclosure control |
| `MEMORYOPS_OUTPUT_GATE_MODE` | `redact` | `redact` or `refuse` |
| request `audience` | `private` | `private` / `team` / `public` |

## Where this sits

- Recall/Admission are **before** the prompt (what may enter context); the Output Gate
  is **after** generation (what the answer may reveal). Together they close the loop
  the deletion-leakage evals (v1.5) measure: not just "deleted memory isn't retrieved"
  but "withheld memory isn't disclosed."
- The Output Gate is a deterministic backstop, not a semantic classifier — it catches
  echoed/near-verbatim disclosure. Paraphrase-level inference is out of scope (and is
  where a future LLM-judge output check would go).
