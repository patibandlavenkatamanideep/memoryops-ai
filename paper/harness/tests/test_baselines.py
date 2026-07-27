"""Ungoverned baselines S1 (full-context), S2 (plain-vector), S3 (rolling-summary).

Each is driven through the neutral contract; kept separate from ``test_contract.py``
because they import the shared LLM/embeddings from the frozen app. Verifies the
contract, retrieval where applicable, scope isolation, and — importantly —
**capability honesty**: an operation a baseline genuinely lacks returns exactly
``unsupported`` (never a faked ok/error), which is the H1 coverage signal.
"""

from __future__ import annotations

import pytest

from paper.harness.types import Capability, OpStatus, Scope

bl = pytest.importorskip("paper.harness.baselines")  # installs the services/api bridge
pytest.importorskip("app.embeddings", reason="frozen app not importable here")

S = Scope("tenantA", "userA")
OTHER = Scope("tenantB", "userB")


@pytest.fixture(params=[bl.s1, bl.s2, bl.s3], ids=["S1", "S2", "S3"])
def adapter(request):
    a = request.param()
    a.reset()
    return a


def _op(adapter, cap: Capability, scope: Scope):
    if cap is Capability.INGEST:
        return adapter.ingest(scope, "seed about tangerines")
    if cap is Capability.QUERY:
        return adapter.query(scope, "tangerines")
    if cap is Capability.FORGET:
        return adapter.forget(scope, "x1")
    if cap is Capability.UPDATE:
        return adapter.update(scope, "x1", "new")
    if cap is Capability.EXPORT_EVIDENCE:
        return adapter.export_evidence(scope)
    raise AssertionError(cap)


@pytest.mark.parametrize("cap", list(Capability))
def test_capabilities_are_honest(adapter, cap):
    adapter.ingest(S, "tangerines are stored in the crate")
    result = _op(adapter, cap, S)
    if cap in adapter.capabilities():
        assert result.status is not OpStatus.UNSUPPORTED
    else:
        assert result.status is OpStatus.UNSUPPORTED, f"{cap}: {result.status}"


def test_reset_clears(adapter):
    adapter.ingest(S, "the vault code is 4821")
    adapter.reset()
    q = adapter.query(S, "vault code")
    assert q.status is OpStatus.OK
    # S1/S2 expose retrieved memories; after reset there are none.
    assert q.used_memory_ids == []


def test_scope_isolation(adapter):
    adapter.ingest(S, "my badge number is 7788 for building access")
    other = adapter.query(OTHER, "what is my badge number")
    assert other.status is OpStatus.OK
    assert other.used_memory_ids == []
    assert all("7788" not in (m.content or "") for m in other.retrieved)


# ── retrieval (S1 full-context, S2 vector) ───────────────────────────────────
def test_full_context_returns_all_history():
    a = bl.s1()
    a.reset()
    a.ingest(S, "my badge number is 7788")
    a.ingest(S, "i like pizza on fridays")
    q = a.query(S, "what is my badge number")
    # Full-context surfaces everything (the ceiling: no retrieval loss).
    contents = " ".join(m.content or "" for m in q.retrieved)
    assert "7788" in contents
    assert len(q.used_memory_ids) == 2


def test_vector_ranks_relevant_memory_first():
    a = bl.s2()
    a.reset()
    a.ingest(S, "my badge number is 7788 for building access")
    a.ingest(S, "i enjoy hiking in the mountains on weekends")
    q = a.query(S, "what is my badge number")
    assert q.status is OpStatus.OK
    assert q.retrieved, "vector baseline retrieved nothing"
    # The badge memory (shares 'badge'/'number') ranks above the hiking distractor.
    assert "7788" in (q.retrieved[0].content or "")


def test_vector_forget_removes_then_absent():
    a = bl.s2()
    a.reset()
    ing = a.ingest(S, "my badge number is 7788")
    a.ingest(S, "unrelated note about coffee")
    assert a.forget(S, ing.memory_ids[0]).status is OpStatus.OK
    q = a.query(S, "what is my badge number")
    assert all("7788" not in (m.content or "") for m in q.retrieved)


def test_baselines_have_no_governance_evidence(adapter):
    adapter.ingest(S, "remember the launch is tuesday")
    assert adapter.export_evidence(S).status is OpStatus.UNSUPPORTED
