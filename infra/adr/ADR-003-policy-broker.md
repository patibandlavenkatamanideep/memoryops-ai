# ADR-003 — Policy broker before storage

## Context
A memory system that stores whatever the model extracts will eventually persist secrets, sensitive
PII, or low-utility noise. Storage must be gated by an explicit, auditable policy decision
(invariant #5: policy-before-storage).

## Decision
Insert a **Policy Broker / Evaluator** between the Extractor and the Write Service. It is the single
choke point that decides one of:

```text
SAVE · PENDING_APPROVAL · BLOCK · DROP_LOW_UTILITY · UPDATE_EXISTING · MERGE_WITH_EXISTING
```

It runs, in order: secret/credential detection → PII/sensitivity classification → utility/dedup
checks → final scoring. Every decision emits an audit event with a human-readable reason.

## Alternatives considered
- **Filter inside the extractor** — couples extraction quality to safety; harder to test/audit in isolation.
- **Post-write moderation** — violates policy-before-storage; secrets briefly persist.
- **Pure LLM judge** — flexible but non-deterministic and unverifiable for hard rules like "block
  API keys". We use deterministic detectors for hard rules and reserve LLM scoring for nuance.

## Trade-offs
- Deterministic regex detectors can over/under-match; mitigated by defense in depth (regex +
  sensitivity classifier + approval queue) and the eval/adversarial suite.
- A single choke point is a potential bottleneck, but it is the property that makes safety provable.

## Consequences
- Implemented in `app/services/policy_broker.py` with detectors in `app/core/redaction.py`.
- Sensitive content with `require_approval_for_sensitive` becomes `pending` (not retrievable).
- Secret-like content is `BLOCK`ed and never written; only an audit record remains.

## Exit strategy
Promote rules into a versioned policy bundle (e.g., OPA/Rego or a rules table) so policies can change
without code deploys; keep the broker interface stable.

## Amendment: the broker governs edits, not only creation

ADR-003 states the broker is "the choke point before storage" and that "nothing
reaches the Write Service without a decision". That held for creation and not for
editing. `PATCH /api/memories/{id}` assigned edited content directly onto the stored
row, so invariant #5 (policy-before-storage) was satisfied on one write path and
silently bypassed on the other.

Consequences, all silent:

- Content that creation would BLOCK — an API key, an injection payload — could be
  introduced by editing an innocuous memory.
- Sensitivity was inherited from the stored row rather than recomputed, so a `low`
  preference edited into medical or financial content kept its `low` label and every
  sensitivity-keyed control (approval gating, recall-gate audience clearance, the
  admission gate) stopped applying to it.
- The embedding was never touched: the row kept the vector of its *previous*
  content. Dense retrieval matched the old text and returned the new text — a stale,
  confidently wrong vector rather than a missing one. On Postgres this was worse
  still, because `update_memory` never persisted `normalized_content` or `embedding`
  at all, so both stayed stale permanently.
- Legal hold was ignored. A hold preserves content; editing destroys it as
  effectively as deleting.

**Decision.** `app/services/update_service.py` is the governed edit path.
`PolicyBroker.evaluate_update` shares the safety rules with creation (secrets and
injection BLOCK, PII elevates sensitivity, medium/high gated behind approval) but
deliberately **omits** two creation-only steps:

- **dedup / `UPDATE_EXISTING`** — `find_similar_active` would match the very memory
  being edited, turning an edit into a reinforcement of itself;
- **low-utility drop** — an edit is not a candidate to discard; dropping it would
  silently retain the old content.

The service also enforces legal hold, recomputes sensitivity from the proposed
content, invalidates and regenerates the embedding, and records before/after content
**hashes** plus the policy decision as audit evidence.

**Concurrency.** `revision` is a row revision owned by the repository and bumped on
every mutation, so lifecycle workers and the control plane share one contract. When
a caller supplies `expected_revision` the write is a compare-and-swap
(`UPDATE ... WHERE revision = :expected`), never an application-side check — the
latter is a time-of-check/time-of-use race, and the embedding call sits squarely
between the read and the write.

**Embedding ordering.** Invalidate-then-regenerate happens inline rather than
marking the vector pending for an async worker. On Postgres `search_candidates`
filters `embedding IS NOT NULL` and BM25 only sees the dense candidate set, so a row
with no vector is invisible to retrieval rather than keyword-degraded — marking
pending would make an edited memory temporarily unfindable. Once true sparse+dense
retrieval and the embedding-lifecycle columns land, this becomes a genuine choice.
If regeneration fails we store no vector, never a stale or cross-space one.

**Still open.** Sensitivity classification only catches structural patterns, so an
edit into `my password is hunter2` or a medical disclosure is not yet detected —
that is the sensitivity-expansion work, not this ADR. Supersession/versioned content
history, and an async re-embedding worker, remain future work.
