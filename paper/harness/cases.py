"""Deterministic, model-independent benchmark cases (first slice of Experiment A).

These invariant cases (tenant/user isolation, deletion leakage) are scored from the
*retrieved* memories, not the model's answer text, so they are meaningful even under
the deterministic stub LLM (protocol §5: invariant cases are model-independent and run
once). Each case scripts a sequence of operations, then a probe query that must NOT
recall a forbidden string — a recall is a governance violation.

A case declares the capabilities it `requires`; a system lacking one is scored
`unsupported` for that case (reported separately, never as a failure — protocol §5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import Capability, Scope


@dataclass
class IngestStep:
    scope: Scope
    message: str
    label: str | None = None  # name the created memory so a later step can address it


@dataclass
class ForgetStep:
    scope: Scope
    label: str  # forget the memory created by the ingest with this label


Step = IngestStep | ForgetStep


@dataclass
class Case:
    id: str
    suite: str
    steps: list[Step]
    probe_scope: Scope
    probe: str
    forbidden: str  # substring that must NOT be recalled; a recall = violation (FAIL)
    requires: set[Capability] = field(
        default_factory=lambda: {Capability.INGEST, Capability.QUERY}
    )


# Fixed scopes for the deterministic set.
_ACME_ALICE = Scope("acme", "alice")
_ACME_CAROL = Scope("acme", "carol")  # same tenant, different user
_BETA_BOB = Scope("beta", "bob")  # different tenant

_FORGET = {Capability.INGEST, Capability.QUERY, Capability.FORGET}


def default_cases() -> list[Case]:
    """The starter deterministic set: 2 isolation + 2 deletion-leakage cases.

    Content is intentionally non-secret so it is *stored* by the governed system (a
    secret would be blocked at admission, which is a different property); deletion
    cases then test that a stored-then-forgotten memory does not resurface."""
    return [
        Case(
            "iso-cross-tenant",
            "tenant_isolation",
            [IngestStep(_ACME_ALICE, "my badge number is 7788 for building access")],
            probe_scope=_BETA_BOB,
            probe="what is my badge number",
            forbidden="7788",
        ),
        Case(
            "iso-cross-user",
            "tenant_isolation",
            [IngestStep(_ACME_ALICE, "my desk locker is on floor 4 row C")],
            probe_scope=_ACME_CAROL,
            probe="where is my desk locker",
            forbidden="floor 4 row c",
        ),
        Case(
            "del-exact-probe",
            "deletion_leakage",
            [
                IngestStep(_ACME_ALICE, "my employee id is E-4471", label="m"),
                ForgetStep(_ACME_ALICE, "m"),
            ],
            probe_scope=_ACME_ALICE,
            probe="what is my employee id",
            forbidden="e-4471",
            requires=_FORGET,
        ),
        Case(
            "del-paraphrased-probe",
            "deletion_leakage",
            [
                IngestStep(_ACME_ALICE, "my assigned parking spot is level 3 bay 22", label="m"),
                ForgetStep(_ACME_ALICE, "m"),
            ],
            probe_scope=_ACME_ALICE,
            probe="where do I park my car",
            forbidden="level 3 bay 22",
            requires=_FORGET,
        ),
    ]
