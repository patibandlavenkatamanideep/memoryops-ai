"""Governed content update — the policy choke point for *edits* (invariant #5).

The bypass this closes
----------------------
`PATCH /api/memories/{id}` assigned edited content straight onto the stored row::

    m.content = patch.content
    m.normalized_content = " ".join(patch.content.lower().split())

Nothing else ran. Consequences, all silent:

  * **The policy broker never saw the edit.** Invariant #5 says the broker runs
    before any write — it did for creation and not for editing. Content that would
    have been BLOCKed at creation (an API key, an injection payload) could be
    introduced by editing an innocuous memory.
  * **Sensitivity was inherited, not recomputed.** A `low` preference edited into
    medical or financial content kept its `low` label, so every downstream control
    keyed on sensitivity — approval gating, the recall gate's audience clearance,
    the admission gate — silently stopped applying.
  * **The embedding was never touched.** The row kept the vector of its *previous*
    content. Dense retrieval then matched the old text while returning the new text:
    a stale, actively wrong vector rather than merely a missing one.
  * **Legal hold was ignored.** A hold preserves content; editing destroys it just
    as effectively as deleting.
  * **The audit event was a bare `memory_updated`** with no before/after evidence.

Design notes
------------
This is not the creation path with a different caller. `PolicyBroker.evaluate_update`
skips dedup (which would match the memory against itself) and the low-utility drop
(which would silently keep the old content), while sharing the safety rules.

Embedding handling is *invalidate-then-regenerate within the same request*. The
alternative — invalidate and mark pending for an async worker — is not yet safe
here: on Postgres `search_candidates` filters `embedding IS NOT NULL`, so a row with
no vector is invisible to dense retrieval rather than keyword-degraded, and BM25 only
sees the dense candidate set. Marking pending would therefore make an edited memory
temporarily unfindable. Regenerating inline keeps the window closed. If regeneration
fails we store **no** vector rather than a stale or cross-space one (consistent with
the embedding-integrity rule): wrong-but-plausible is worse than absent.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..core.redaction import scan
from ..core.reliability import safe_call
from ..db import governance as gov
from ..db.entities import StoredMemory, StoredSettings
from ..embeddings import embed
from ..schemas.memory import CandidateMemory, Decision, Sensitivity, Status
from .policy_broker import PolicyBroker


def normalize(content: str) -> str:
    """Canonical normalized form. Single definition, shared by create and update."""
    return " ".join(content.lower().split())


def content_hash(content: str) -> str:
    """Short, content-free-in-audit digest of a memory's text.

    Audit evidence records *hashes*, never the before/after text: the audit trail is
    read by operators who may not be cleared for the memory itself, and a deleted
    memory's content must not survive in its audit events.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class UpdateRejected(Exception):
    """The edit was refused by policy; the memory is unchanged."""

    def __init__(self, reason: str, *, labels: list[str] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.labels = labels or []


class LegalHoldActive(Exception):
    """The memory is under legal hold; its content is preserved, not editable."""


class RevisionConflict(Exception):
    """Another writer changed the memory since the caller read it."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"expected revision {expected}, memory is at {actual}")
        self.expected = expected
        self.actual = actual


@dataclass
class UpdateResult:
    memory: StoredMemory
    decision: Decision
    reason: str
    audit_action: str
    #: Content-free evidence for the audit event.
    evidence: dict = field(default_factory=dict)


def apply_content_update(
    memory: StoredMemory,
    new_content: str,
    *,
    broker: PolicyBroker,
    settings: StoredSettings,
    expected_revision: int | None = None,
    now: datetime | None = None,
) -> UpdateResult:
    """Run an edit through governance and return the mutated memory.

    Mutates ``memory`` in place (the caller holds it inside `repo.transaction`, so a
    rollback undoes this) and returns the decision plus audit evidence. The caller is
    responsible for persisting via ``repo.update_memory_checked`` when
    ``expected_revision`` was supplied, so the concurrency guard is enforced by the
    database rather than by a check here.

    Raises:
        LegalHoldActive: the memory's content is preserved and may not be edited.
        UpdateRejected: policy BLOCKed the proposed content.
    """
    now = now or datetime.now(UTC)

    # ── 1. preservation and concurrency, before any evaluation ───────────────
    # Legal hold is a *preservation* control. Editing content destroys the held
    # text as surely as deleting the row, so a hold blocks edits exactly as it
    # blocks deletion. Governance-only changes (approve/archive) stay permitted —
    # they do not touch content.
    if gov.is_legal_hold(memory):
        raise LegalHoldActive("memory is under legal hold; content cannot be edited")

    # NOTE: no Python-side revision comparison here. It would be a time-of-check /
    # time-of-use race — two requests can both read revision N, both pass, and both
    # write, the second clobbering the first. Embedding generation below sits between
    # the read and the write, widening the window further. The guard belongs in the
    # write itself: the caller persists via `repo.update_memory_checked(...)`, whose
    # conditional UPDATE lets the database arbitrate.
    current_revision = getattr(memory, "revision", 1)

    previous_hash = content_hash(memory.content)
    previous_sensitivity = memory.sensitivity

    # ── 2. governance on the *proposed* content ──────────────────────────────
    candidate = CandidateMemory(
        content=new_content,
        type=memory.memory_type,
        # Start from `low` so sensitivity is *recomputed* from the new text rather
        # than inherited from the stored row. Inheriting is what let an edit into
        # medical or financial content keep a `low` label.
        sensitivity=Sensitivity.low,
        importance=memory.importance,
        confidence=memory.confidence,
        reason="content edit",
    )
    outcome = broker.evaluate_update(candidate, settings=settings)

    if outcome.decision is Decision.BLOCK:
        # Fail closed: the stored memory keeps its previous content untouched.
        raise UpdateRejected(outcome.reason)

    # ── 3. apply, atomically with the revision bump ──────────────────────────
    memory.content = new_content
    memory.normalized_content = normalize(new_content)
    memory.sensitivity = outcome.candidate.sensitivity
    memory.updated_at = now
    # The revision is bumped by the repository as part of the write, never assigned
    # here — a value computed before the embedding call would be stale by the time
    # it reached the database.

    # Invalidate first, so no code path can leave the previous vector attached to
    # the new text. If regeneration fails, the memory keeps *no* vector rather than
    # a stale one — recoverable and re-embeddable, unlike a confidently wrong match.
    memory.embedding = []
    memory.embedding = safe_call(
        lambda: embed(new_content), default=[], label="embed_update"
    )

    audit_action = "memory_content_updated"
    if outcome.decision is Decision.PENDING_APPROVAL:
        # Re-gated: the edit introduced sensitive content, so it returns to the
        # approval queue instead of silently remaining active.
        memory.status = Status.pending
        audit_action = "memory_content_update_pending_approval"

    assessment = scan(new_content).assessment
    evidence = {
        # Classification evidence is category/rule identifiers only — never the
        # matched password, diagnosis, salary, address, or regex excerpt. The audit
        # trail is read by operators who may not be cleared for the memory itself.
        "sensitivity_categories": list(assessment.categories),
        "sensitivity_rule_ids": list(assessment.rule_ids),
        "sensitivity_finding_count": len(assessment.findings),
        "previous_content_hash": previous_hash,
        "new_content_hash": content_hash(new_content),
        "previous_sensitivity": previous_sensitivity.value,
        "new_sensitivity": memory.sensitivity.value,
        "sensitivity_changed": previous_sensitivity != memory.sensitivity,
        "decision": outcome.decision.value,
        "previous_revision": current_revision,
        "embedding_regenerated": bool(memory.embedding),
        "policy_version": POLICY_VERSION,
    }
    return UpdateResult(
        memory=memory,
        decision=outcome.decision,
        reason=outcome.reason,
        audit_action=audit_action,
        evidence=evidence,
    )


#: Bumped whenever the update policy's *rules* change, so an audit event can be
#: interpreted against the policy that actually produced it.
POLICY_VERSION = "content-update-v1"
