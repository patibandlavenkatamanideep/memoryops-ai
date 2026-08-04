"""Legal status transitions for `PATCH /api/memories/{id}`.

Why this exists
---------------
`MemoryPatch.status` accepted the **entire** `Status` enum and the handler assigned
it directly, with an `elif` chain that only named `active` / `rejected` / `archived`.
Any other value fell through and was written verbatim. `status="deleted"` therefore
produced a row that was:

  * hidden from retrieval (invariant #2 excludes `deleted`),
  * but with ``deleted_at = None``, so retention and compaction — which key off
    ``deleted_at`` — never reclaimed it,
  * with no tombstone and no lineage propagation,
  * audited only as a generic ``memory_updated``,
  * **and it succeeded while the memory was under legal hold**, which the real
    ``DELETE`` route correctly refuses with 409.

That is worse than an ordinary bypass: the record ends up in a limbo that neither
the deletion guarantee nor the preservation guarantee covers — invisible to the
user, un-compactable by the system, and still reported as held.

The fix is to validate the **transition**, not just the requested value: a target
status is legal only from specific current states.

Deletion stays exclusive to ``DELETE /api/memories/{memory_id}``, which is the only
path that performs legal-hold verification, ``deleted_at`` assignment, tombstone
creation, lineage propagation, deletion audit evidence, and compaction eligibility.

Compatibility
-------------
The `status` field is **kept** — this is a behavioural correction for invalid
transitions, not a removal. Every transition real clients use (approve, reject,
archive, restore) still works unchanged, so the `1.x` additive-compatibility promise
holds: no public request or response field is removed.
"""

from __future__ import annotations

from ..schemas.memory import Status

# Statuses `PATCH` never supports, whatever the current state.
#   deleted — must go through the deletion workflow (legal hold, tombstone, lineage)
#   pending — assigned by the policy broker at write time, never by a client
#   blocked — a policy-broker verdict, never a client-assigned state
UNSUPPORTED_PATCH_STATUSES: frozenset[Status] = frozenset(
    {Status.deleted, Status.pending, Status.blocked}
)

# (current, requested) -> the governance action it represents.
ALLOWED_TRANSITIONS: dict[tuple[Status, Status], str] = {
    (Status.pending, Status.active): "approve",
    (Status.pending, Status.rejected): "reject",
    (Status.active, Status.archived): "archive",
    (Status.archived, Status.active): "restore",
}

# Human-readable action -> (audit action, audit reason).
TRANSITION_AUDIT: dict[str, tuple[str, str]] = {
    "approve": ("memory_approved", "pending memory approved"),
    "reject": ("memory_rejected", "pending memory rejected"),
    "archive": ("memory_archived", "memory archived"),
    "restore": ("memory_restored", "archived memory restored"),
}


class EmptyPatch(ValueError):
    """The patch requests no change at all (→ 422)."""


class UnsupportedStatus(ValueError):
    """The requested status is never settable via PATCH (→ 422)."""


class InvalidTransition(ValueError):
    """The requested status is settable, but not from the current state (→ 409)."""


def validate_transition(current: Status, requested: Status) -> str:
    """Return the governance action for a legal transition, else raise.

    Raises:
        UnsupportedStatus: the target is never valid on this route (422).
        InvalidTransition: the target is valid in general, but not from
            ``current`` (409).
    """
    if requested in UNSUPPORTED_PATCH_STATUSES:
        raise UnsupportedStatus(
            f"status '{requested.value}' must be changed through its dedicated "
            "governance workflow, not PATCH"
        )
    action = ALLOWED_TRANSITIONS.get((current, requested))
    if action is None:
        raise InvalidTransition(
            f"cannot change status from '{current.value}' to '{requested.value}'"
        )
    return action


#: Fields whose presence means the caller is editing the memory's own substance,
#: as opposed to moving it through the governance state machine.
EDIT_FIELDS: tuple[str, ...] = ("content", "importance", "confidence")


def derive_patch_actions(
    *,
    has_content: bool,
    has_importance: bool,
    has_confidence: bool,
    transition: str | None,
) -> frozenset[str]:
    """Every governance action one PATCH body requests.

    A PATCH is not one action. ``{"content": ..., "status": "active"}`` edits the
    memory *and* approves it, and the two are governed differently: `edit` has a
    self permission, `approve` deliberately does not. Authorizing only the
    transition would let ``memory:approve:tenant`` implicitly grant a content edit
    — the approver could rewrite what they are approving, in the same request that
    approves it, and the audit trail would record only the approval.

    So the caller must hold *every* applicable permission, not any one of them.

    Raises:
        EmptyPatch: the body changes nothing (→ 422). A patch that requests no
            action has no permission to check, and a request with nothing to
            authorize must not be treated as authorized.
    """
    actions: set[str] = set()
    if has_content or has_importance or has_confidence:
        actions.add("edit")
    if transition is not None:
        actions.add(transition)
    if not actions:
        raise EmptyPatch(
            "patch requests no change: provide at least one of "
            f"{', '.join(EDIT_FIELDS)}, status"
        )
    return frozenset(actions)
