"""The transition matrix itself, independent of HTTP.

Route-level behaviour is covered in `test_status_transition_bypass.py`; this pins
the policy so a future edit to the table is a deliberate, visible change.
"""

from __future__ import annotations

import itertools

import pytest

from app.schemas.memory import MemoryPatch, Status
from app.services.status_transitions import (
    ALLOWED_TRANSITIONS,
    EDIT_FIELDS,
    TRANSITION_AUDIT,
    UNSUPPORTED_PATCH_STATUSES,
    EmptyPatch,
    InvalidTransition,
    UnsupportedStatus,
    derive_patch_actions,
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


# ── one PATCH, many actions ──────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"has_content": True}, {"edit"}),
        ({"has_importance": True}, {"edit"}),
        ({"has_confidence": True}, {"edit"}),
        # Every edit field collapses to the same single action.
        ({"has_content": True, "has_importance": True, "has_confidence": True}, {"edit"}),
        ({"transition": "approve"}, {"approve"}),
        ({"transition": "archive"}, {"archive"}),
        # The case the conjunctive rule exists for.
        ({"has_content": True, "transition": "approve"}, {"edit", "approve"}),
        ({"has_importance": True, "transition": "restore"}, {"edit", "restore"}),
    ],
)
def test_derived_actions_cover_everything_the_body_requests(kwargs, expected):
    call = {
        "has_content": False,
        "has_importance": False,
        "has_confidence": False,
        "transition": None,
        **kwargs,
    }
    assert derive_patch_actions(**call) == expected


def test_an_edit_plus_transition_is_two_actions_not_one():
    """The reason authorization cannot key off the transition alone.

    `approve` has no self permission by design; `edit` does. If one PATCH resolved
    to a single action, a tenant approver could rewrite a memory's content in the
    same request that approves it, and the audit would record only the approval.
    Both permissions must be held.
    """
    actions = derive_patch_actions(
        has_content=True,
        has_importance=False,
        has_confidence=False,
        transition="approve",
    )
    assert actions == {"edit", "approve"}
    assert len(actions) == 2, "an edit must not be absorbed into the transition"


def test_a_patch_that_changes_nothing_is_refused():
    """No action means no permission to check — it must not resolve to 'allowed'."""
    with pytest.raises(EmptyPatch):
        derive_patch_actions(
            has_content=False,
            has_importance=False,
            has_confidence=False,
            transition=None,
        )


def test_edit_fields_matches_the_schema_fields_that_produce_an_edit():
    """Adding an editable field without adding it here would let it through
    unauthorized — the field would mutate the memory but contribute no action."""
    schema_fields = set(MemoryPatch.model_fields)
    governance_fields = {"tenant_id", "user_id", "status", "expected_revision"}
    assert set(EDIT_FIELDS) == schema_fields - governance_fields


def test_changes_nothing_agrees_with_the_derivation():
    scoped = {"tenant_id": "acme", "user_id": "alice"}
    assert MemoryPatch(**scoped).changes_nothing is True
    assert MemoryPatch(**scoped, expected_revision=3).changes_nothing is True, (
        "a revision guard alone still requests no change"
    )
    for field in EDIT_FIELDS:
        value = {"content": "x", "importance": 5, "confidence": 0.5}[field]
        assert MemoryPatch(**scoped, **{field: value}).changes_nothing is False
    assert MemoryPatch(**scoped, status=Status.active).changes_nothing is False
