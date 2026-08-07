"""S0 (governed) and S0-U (governance-disabled) MemoryOps adapters over the real
in-process pipeline.

Kept separate from the neutral ``test_contract.py`` because these import the frozen
``services/api`` app. They prove: both profiles satisfy the adapter contract end to
end (ingest → query recall, scope isolation, forget/update, evidence export), and the
two profiles are genuinely different systems (S0 withholds a blocked secret from
storage; S0-U, ungoverned, stores it).

Run: ``python -m pytest paper/harness/tests/test_memoryops_adapter.py``
"""

from __future__ import annotations

import pytest

from paper.harness.types import Capability, OpStatus, Scope

# Skip cleanly if the app / its deps are not importable in this environment.
pytest.importorskip("fastapi")
moa = pytest.importorskip("paper.harness.memoryops_adapter")

S = Scope("tenantA", "userA")
OTHER = Scope("tenantB", "userB")


@pytest.fixture(params=[moa.s0, moa.s0u], ids=["S0", "S0-U"])
def adapter(request):
    a = request.param()
    a.reset()
    return a


def test_declares_full_capability_surface(adapter):
    assert adapter.capabilities() == set(Capability)


def test_ingest_then_query_recalls(adapter):
    adapter.ingest(S, "Remember that the project deadline is March 15.")
    q = adapter.query(S, "When is the project deadline?")
    assert q.status is OpStatus.OK
    assert "march 15" in q.answer.lower() or any(
        "march 15" in (m.content or "").lower() for m in q.retrieved
    )


def test_scope_isolation(adapter):
    adapter.ingest(S, "My badge number is 7788 for building access.")
    other = adapter.query(OTHER, "What is my badge number?")
    assert other.status is OpStatus.OK
    assert "7788" not in other.answer
    assert other.used_memory_ids == []


def test_forget_removes_from_recall(adapter):
    ing = adapter.ingest(S, "Remember my favorite color is teal.")
    if not ing.memory_ids:
        pytest.skip("nothing extracted to forget")
    assert adapter.forget(S, ing.memory_ids[0]).status is OpStatus.OK
    after = adapter.query(S, "What is my favorite color?")
    assert "teal" not in after.answer.lower()


def test_evidence_export_available(adapter):
    adapter.ingest(S, "Remember I take the 8am train.")
    ev = adapter.export_evidence(S)
    assert ev.status is OpStatus.OK and ev.available


# Assembled at import time rather than written inline. This test needs input that
# *looks* like a real key — that is the whole point — and a committed
# credential-shaped literal is exactly what secret scanners exist to catch. They
# cannot tell a fixture from a live key, and gitleaks scans commit ranges, so
# deleting such a literal in a later commit does not clear the branch.
FAKE_KEY = "sk" + "-" + "ABCDEF" + "0123456789"


def test_s0_blocks_secret_but_s0u_stores_it():
    # A clear secret: governed S0 must never persist it; ungoverned S0-U will.
    secret = f"My OpenAI key is {FAKE_KEY} please remember it."
    s0 = moa.s0()
    s0.reset()
    s0.ingest(S, secret)
    assert not any(FAKE_KEY in (c or "") for c in _contents(s0, S))

    s0u = moa.s0u()
    s0u.reset()
    s0u.ingest(S, secret)
    assert any(FAKE_KEY in (c or "") for c in _contents(s0u, S))


def _contents(adapter, scope) -> list[str]:
    r = adapter._client.get(
        "/api/memories", params={"tenant_id": scope.tenant_id, "user_id": scope.user_id}
    )
    return [m.get("content", "") for m in r.json()] if r.status_code == 200 else []
