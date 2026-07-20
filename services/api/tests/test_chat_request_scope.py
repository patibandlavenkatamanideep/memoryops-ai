"""ChatRequest scope validation (schema boundary).

An empty tenant_id / user_id is invalid input and must be rejected at the schema
boundary (422) rather than flowed through the pipeline with no owner — otherwise an
empty-scope request reaches backend-specific paths (e.g. Postgres loop-evidence
recording, which requires a tenant) and can crash instead of degrading (invariant #4).
Odd-but-*non-empty* ids (wildcards, injection-looking strings, whitespace) are still
accepted and defused by parameterized scoping — that is what the isolation evals probe.

These are pure schema tests: no app, no DB.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.memory import ChatRequest


@pytest.mark.parametrize("tenant_id,user_id", [("", "u"), ("t", ""), ("", "")])
def test_empty_scope_is_rejected(tenant_id: str, user_id: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(tenant_id=tenant_id, user_id=user_id, message="hi")


@pytest.mark.parametrize(
    "tenant_id,user_id",
    [
        ("acme", "alice"),          # ordinary
        ("%", "%"),                 # wildcard-looking
        ("   ", "user_eval"),       # whitespace (non-empty)
        ("' OR '1'='1", "user"),    # injection-looking
        ("victim_tenant\n", "u"),   # trailing newline
    ],
)
def test_odd_but_nonempty_scope_is_accepted(tenant_id: str, user_id: str) -> None:
    # Non-empty but adversarial ids are allowed through — scoping (not the schema)
    # is what prevents cross-tenant leakage, and the isolation evals prove it.
    req = ChatRequest(tenant_id=tenant_id, user_id=user_id, message="hi")
    assert req.tenant_id == tenant_id
    assert req.user_id == user_id


def test_max_length_still_bounds_scope() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(tenant_id="t" * 201, user_id="u", message="hi")
