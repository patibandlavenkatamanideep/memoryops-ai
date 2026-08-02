"""The transition matrix itself, independent of HTTP.

Route-level behaviour is covered in `test_status_transition_bypass.py`; this pins
the policy so a future edit to the table is a deliberate, visible change.
"""

from __future__ import annotations

import itertools

import pytest

from app.schemas.memory import Status
from app.services.status_transitions import (
    ALLOWED_TRANSITIONS,
    TRANSITION_AUDIT,
    UNSUPPORTED_PATCH_STATUSES,
    InvalidTransition,
    UnsupportedStatus,
    validate_transition,
)


def test_exactly_four_transitions_are_allowed():
    assert set(ALLOWED_TRANSITIONS) == {
        (Status.pending, Status.active),
        (Status.pending, Status.rejected),
        (Status.active, Status.archived),
        (Status.archived, Status.active),
    }


@pytest.mark.parametrize(
    ("current", "requested", "action"),
    [
        (Status.pending, Status.active, "approve"),
        (Status.pending, Status.rejected, "reject"),
        (Status.active, Status.archived, "archive"),
        (Status.archived, Status.active, "restore"),
    ],
)
def test_allowed_transitions_return_their_action(current, requested, action):
    assert validate_transition(current, requested) == action


@pytest.mark.parametrize("target", sorted(UNSUPPORTED_PATCH_STATUSES, key=lambda s: s.value))
@pytest.mark.parametrize("current", list(Status))
def test_unsupported_targets_raise_regardless_of_current_state(current, target):
    """deleted/pending/blocked are never settable via PATCH, from any state.

    `deleted` is the one that mattered: it bypassed legal hold, `deleted_at`,
    tombstones, lineage, deletion audit, and compaction eligibility.
    """
    with pytest.raises(UnsupportedStatus):
        validate_transition(current, target)


def test_unsupported_set_is_exactly_the_three_documented_statuses():
    assert UNSUPPORTED_PATCH_STATUSES == frozenset(
        {Status.deleted, Status.pending, Status.blocked}
    )


def test_every_other_combination_is_an_invalid_transition():
    """Fail closed: anything not explicitly allowed is refused, including no-ops."""
    for current, requested in itertools.product(Status, Status):
        if requested in UNSUPPORTED_PATCH_STATUSES:
            continue  # covered above, raises UnsupportedStatus
        if (current, requested) in ALLOWED_TRANSITIONS:
            continue
        with pytest.raises(InvalidTransition):
            validate_transition(current, requested)


def test_no_transition_out_of_deleted_is_allowed():
    """Deleted is terminal in the matrix as well as at the route (which 404s first)."""
    for requested in Status:
        with pytest.raises((UnsupportedStatus, InvalidTransition)):
            validate_transition(Status.deleted, requested)


def test_every_allowed_transition_has_a_distinct_audit_action():
    actions = [TRANSITION_AUDIT[a][0] for a in ALLOWED_TRANSITIONS.values()]
    assert len(actions) == len(set(actions)), "each transition needs its own audit action"
    # Restore must not be recorded as an approval — the old handler keyed the audit
    # action off the target status alone, so archived→active and pending→active
    # were indistinguishable in the trail.
    assert TRANSITION_AUDIT["restore"][0] == "memory_restored"
    assert TRANSITION_AUDIT["approve"][0] == "memory_approved"


def test_audit_table_covers_every_allowed_action():
    assert set(TRANSITION_AUDIT) >= set(ALLOWED_TRANSITIONS.values())
