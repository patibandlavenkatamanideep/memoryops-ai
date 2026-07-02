# Context Admission Gate + Memory Usage Trace

Retrieval + ranking answer *"is this memory **relevant**?"*. MemoryOps also answers
*"is this memory **allowed** into context for this turn — and can it prove why?"*
(v1.3, [ADR-017](../infra/adr/ADR-017-context-admission-gate.md)).

The **Context Admission Gate** runs between the ranker and the context composer:

```
retrieve → rank → [ADMISSION GATE] → compose → LLM
```

For each ranked candidate it returns an explainable verdict; only `ALLOW` memories
reach the LLM. The **Memory Usage Trace** on the chat response then shows the full
trail behind the answer — which memories were used, where they came from, when they
were stored, whether they were still valid, and why each was (or wasn't) admitted.

> **Defense-in-depth, never additive.** The gate only ever *removes* memory from
> context. It cannot resurrect, promote, or add memory, so it strengthens tenant
> isolation (invariant #1) and the deletion guarantee (#2). It is no-throw (#4):
> on any failure the read degrades and the response is never blocked.

## Admission decisions

| Decision | Meaning | Default |
|----------|---------|---------|
| `ALLOW` | Relevant, active, consent-granted, tenant-scoped | — |
| `BLOCK_WRONG_TENANT` | Out of tenant/user scope (repo already filters; belt-and-suspenders) | on |
| `BLOCK_DELETED` | Soft-deleted memory | on |
| `BLOCK_ARCHIVED` | Archived memory | on |
| `BLOCK_INACTIVE` | `pending` / `rejected` / `blocked` status | on |
| `BLOCK_CONSENT_WITHDRAWN` | Consent withdrawn or expired (still-active memory) | on |
| `BLOCK_EXPIRED` | Retention window elapsed (and not hold/pin/protect exempt) | on |
| `BLOCK_TOMBSTONED_ANCESTOR` | Derived from a deleted/tombstoned/purged ancestor (v1.4) | on |
| `BLOCK_SENSITIVE` | `sensitivity='high'` | **opt-in** |
| `BLOCK_LOW_CONFIDENCE` | Ranked score below `admission_min_score` | **opt-in** |

The load-bearing verdicts are `BLOCK_CONSENT_WITHDRAWN` and `BLOCK_EXPIRED`: they
deny **active** memory whose governance turned against admission *before* the next
retention-worker pass removes it — closing the window between a governance change
and its effect on output. Legal hold / pin / protect are *preservation* controls
and are therefore retention-exempt (never blocked by `BLOCK_EXPIRED`).

## The Memory Usage Trace on the chat response

`POST /api/chat` responses include an optional `trace` block (present when the trace
is enabled):

```json
{
  "trace": {
    "response_id": "resp_123",
    "memories_used": [
      {
        "memory_id": "mem_001",
        "memory_type": "preference",
        "content_preview": "User prefers Vendor X for cloud.",
        "source": {"kind": "chat", "excerpt": "..."},
        "stored_at": "2026-07-01T10:12:00Z",
        "status": "active",
        "sensitivity": "low",
        "consent_status": "granted",
        "retention_status": "none",
        "admission_decision": "ALLOW",
        "admission_reason": "relevant, active, consent-granted, tenant-scoped",
        "retrieval_score": 0.86,
        "score_breakdown": {"vector_similarity": 0.9, "keyword_score": 0.5, "...": 0.0}
      }
    ],
    "memories_blocked": [],
    "admission_counts": {"ALLOW": 1}
  }
}
```

- `memories_used` — admitted into context (shaped the answer). In observe-only
  (shadow) mode these still carry their true verdict, so an entry can appear here
  with a `BLOCK_*` decision meaning *"would have been blocked if enforced"*.
- `memories_blocked` — retrieved but denied admission, each with its `BLOCK_*`
  decision + reason.
- `admission_counts` — histogram of decisions for the turn.
- `retention_status` — `active` (within window) | `expired` | `exempt`
  (hold/pin/protect) | `none` (no window recorded).

Content is surfaced as a short **preview** only (same tenant trust boundary as the
existing `used_memories`).

## Observability + audit

- **Metric.** `memoryops_admission_decisions_total{decision}` — content-free,
  low-cardinality counter on `GET /metrics` (see [observability.md](observability.md)).
- **Audit.** When memory is blocked (enforced mode), one per-turn
  `context_admission_blocked` event records the blocked count, decision histogram,
  and blocked memory ids (content-free) — invariant #7.
- **Loop timeline.** The `memory_read` loop's `EXECUTED` event carries
  `admission_decisions`.

## Configuration

| Setting | Env | Default | Effect |
|---------|-----|---------|--------|
| `admission_gate_enabled` | `MEMORYOPS_ADMISSION_GATE` | `true` | `false` = observe-only (shadow) mode: traced/counted but nothing removed |
| `memory_trace_enabled` | `MEMORYOPS_MEMORY_TRACE` | `true` | Attach the `trace` block to responses |
| `admission_block_sensitive` | `MEMORYOPS_ADMISSION_BLOCK_SENSITIVE` | `false` | Block `sensitivity='high'` from context |
| `admission_min_score` | `MEMORYOPS_ADMISSION_MIN_SCORE` | `0.0` | Block ranked score below this (`0` disables) |

With the defaults, no observable behavior changes: deleted/archived/wrong-tenant
memory can't be retrieved anyway, and the stricter gates are off. The gate becomes
load-bearing once consent is withdrawn or a retention window elapses on active
memory.

## Not in scope (later phases)

- Freshness / `last_validated_at` staleness scoring (v1.5).
- Tombstone lineage + derived-artifact blocking + deleted-memory leakage evals (v1.3+).
- Recall Gate / Output Gate / audience-aware + third-party consent (v1.4).
