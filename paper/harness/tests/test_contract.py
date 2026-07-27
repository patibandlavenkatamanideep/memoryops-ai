"""Deterministic contract tests every ``MemorySystemAdapter`` must satisfy.

These run against *any* adapter (parametrize new systems in as they are built). They
check the neutral guarantees the protocol depends on — scope isolation, reset, and —
critically — that ``capabilities()`` is *honest*: an operation whose capability is
declared must not report ``unsupported``, and one whose capability is absent must
report exactly ``unsupported`` (never a faked ok/error). This is what lets the study
report unsupported capability separately from failure (protocol §5).

Run: ``python -m pytest paper/harness/tests``
"""

from __future__ import annotations

import pytest

from paper.harness.reference import ReferenceDictAdapter
from paper.harness.types import Capability, OpStatus, Scope

# Register each adapter under test here.
ADAPTERS = [ReferenceDictAdapter]

S = Scope("t1", "u1")
OTHER = Scope("t2", "u2")


@pytest.fixture(params=ADAPTERS, ids=lambda a: a.name)
def adapter(request):
    a = request.param()
    a.reset()
    yield a


def _op(adapter, cap: Capability, scope: Scope):
    """Invoke the operation for a capability and return its result object."""
    if cap is Capability.INGEST:
        return adapter.ingest(scope, "seed message about mango pickles")
    if cap is Capability.QUERY:
        return adapter.query(scope, "mango pickles")
    if cap is Capability.FORGET:
        return adapter.forget(scope, "m1")
    if cap is Capability.UPDATE:
        return adapter.update(scope, "m1", "updated content")
    if cap is Capability.EXPORT_EVIDENCE:
        return adapter.export_evidence(scope)
    raise AssertionError(cap)


def test_capabilities_is_a_capability_set(adapter):
    caps = adapter.capabilities()
    assert isinstance(caps, set)
    assert caps <= set(Capability)
    assert isinstance(adapter.name, str) and adapter.name


def test_reset_is_idempotent_and_clears(adapter):
    adapter.ingest(S, "remember the vault code is 4821")
    adapter.reset()
    adapter.reset()  # twice — must not raise
    q = adapter.query(S, "vault code")
    assert q.status is OpStatus.OK
    assert q.answer == ""  # cleared


@pytest.mark.parametrize("cap", list(Capability))
def test_capabilities_are_honest(adapter, cap):
    # Ensure m1 exists so forget/update address a real id where supported.
    adapter.ingest(S, "mango pickles are stored in the pantry")
    result = _op(adapter, cap, S)
    if cap in adapter.capabilities():
        # A declared capability must never answer 'unsupported'.
        assert result.status is not OpStatus.UNSUPPORTED, f"{cap} declared but unsupported"
    else:
        # An undeclared capability must answer exactly 'unsupported' (not faked).
        assert result.status is OpStatus.UNSUPPORTED, f"{cap} absent but status={result.status}"


def test_ingest_then_query_recalls(adapter):
    if Capability.INGEST not in adapter.capabilities():
        pytest.skip("adapter cannot ingest")
    ing = adapter.ingest(S, "the meeting is in the blue conference room")
    assert ing.status is OpStatus.OK and ing.memory_ids
    q = adapter.query(S, "which conference room is the meeting")
    assert q.status is OpStatus.OK
    assert "blue" in q.answer.lower()


def test_scope_isolation(adapter):
    if Capability.INGEST not in adapter.capabilities():
        pytest.skip("adapter cannot ingest")
    adapter.ingest(S, "my private diagnosis is condition X")
    other = adapter.query(OTHER, "diagnosis")
    # A different tenant/user must not recall S's memory (invariant #1).
    assert "condition x" not in other.answer.lower()
    assert other.used_memory_ids == []
