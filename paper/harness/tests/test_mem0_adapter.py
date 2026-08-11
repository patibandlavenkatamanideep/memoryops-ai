"""S4 Mem0 adapter — real product API, no paid provider, no leaked state.

Skipped wholesale when the `benchmark` extra is absent, which is the default for the
ordinary test environment. The comparison is optional; the guarantees below are not.

The load-bearing assertion is `test_no_llm_call_occurs_during_ingest_or_query`: Mem0
constructs an LLM eagerly in `Memory.__init__`, so "we passed infer=False" is not by
itself evidence that nothing was invoked. The injected model raises if called, and
that is what makes "0 provider calls" a checked property rather than a claim.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from paper.harness import mem0_adapter as m4
from paper.harness.adapter import MemorySystemAdapter
from paper.harness.cases import default_cases
from paper.harness.runner import run_suite
from paper.harness.types import Capability, OpStatus, Outcome, Scope

pytestmark = pytest.mark.skipif(
    not m4.available(), reason="benchmark extra not installed (mem0ai/langchain)"
)

_A = Scope("acme", "alice")
_B = Scope("beta", "bob")


@pytest.fixture
def adapter():
    a = m4.s4()
    try:
        yield a
    finally:
        a.close()


# ── contract ─────────────────────────────────────────────────────────────────
def test_satisfies_the_adapter_protocol(adapter):
    assert isinstance(adapter, MemorySystemAdapter)
    assert adapter.name == "S4"


def test_declares_only_capabilities_it_has(adapter):
    caps = adapter.capabilities()
    assert {Capability.INGEST, Capability.QUERY, Capability.FORGET} <= caps
    # Mem0 is not a governance product; claiming evidence export would fabricate a
    # capability and turn a legitimate `unsupported` into a false comparison.
    assert Capability.EXPORT_EVIDENCE not in caps
    assert adapter.export_evidence(_A).status is OpStatus.UNSUPPORTED


# ── provider-free guarantee ──────────────────────────────────────────────────
def test_no_llm_call_occurs_during_ingest_or_query(adapter):
    """The injected chat model raises if invoked; reaching the asserts means it wasn't."""
    ing = adapter.ingest(_A, "my badge number is 7788 for building access")
    assert ing.status is OpStatus.OK, ing.detail
    q = adapter.query(_A, "what is my badge number")
    assert q.status is OpStatus.OK, q.detail


def test_runs_without_any_provider_credentials(monkeypatch):
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    a = m4.s4()
    try:
        assert a.ingest(_A, "my employee id is E-4471").status is OpStatus.OK
    finally:
        a.close()


def test_ingest_uses_infer_false(adapter, monkeypatch):
    """Deduction off is what keeps the LLM out of the path; pin it explicitly."""
    seen = {}
    real_add = adapter._memory.add

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real_add(*args, **kwargs)

    monkeypatch.setattr(adapter._memory, "add", spy)
    adapter.ingest(_A, "my desk locker is on floor 4 row C")
    assert seen.get("infer") is False


# ── scope mapping ────────────────────────────────────────────────────────────
def test_scope_is_mapped_to_a_compound_identity():
    """Mem0 has no tenant concept; the compound id is the closest honest mapping."""
    assert m4.Mem0Adapter._identity(_A) == "acme:alice"
    assert m4.Mem0Adapter._identity(_A) != m4.Mem0Adapter._identity(_B)


def test_one_scope_does_not_see_another(adapter):
    adapter.ingest(_A, "my badge number is 7788 for building access")
    result = adapter.query(_B, "what is my badge number")
    assert result.status is OpStatus.OK
    joined = " ".join((r.content or "") for r in result.retrieved).lower()
    assert "7788" not in joined


# ── deletion goes through Mem0's API ─────────────────────────────────────────
def test_delete_uses_the_product_api_and_removes_the_memory(adapter):
    ing = adapter.ingest(_A, "my employee id is E-4471")
    assert ing.memory_ids, "no memory id returned"
    assert adapter.forget(_A, ing.memory_ids[0]).status is OpStatus.OK
    after = adapter.query(_A, "what is my employee id")
    joined = " ".join((r.content or "") for r in after.retrieved).lower()
    assert "e-4471" not in joined


def test_deleting_an_unknown_id_is_an_error_not_unsupported(adapter):
    """A broken integration must never masquerade as a missing capability."""
    result = adapter.forget(_A, "00000000-0000-4000-8000-000000000000")
    assert result.status is not OpStatus.UNSUPPORTED


# ── isolation of state ───────────────────────────────────────────────────────
def test_vector_state_is_temporary_and_outside_the_repository(adapter):
    repo = Path(__file__).resolve().parents[3]
    path = Path(adapter._dir)
    assert path.exists()
    assert repo not in path.parents, "benchmark state must not be written into the repo"
    assert str(path).startswith(os.path.realpath("/") + "private") or "/tmp" in str(path) \
        or str(path).startswith("/var"), f"expected a temp dir, got {path}"


def test_close_removes_state_and_is_idempotent(adapter):
    path = Path(adapter._dir)
    adapter.close()
    assert not path.exists()
    adapter.close()  # must not raise


def test_reset_yields_an_empty_store(adapter):
    adapter.ingest(_A, "my assigned parking spot is level 3 bay 22")
    adapter.reset()
    after = adapter.query(_A, "where do I park my car")
    joined = " ".join((r.content or "") for r in after.retrieved).lower()
    assert "level 3 bay 22" not in joined


# ── outcomes ─────────────────────────────────────────────────────────────────
def test_runs_the_real_cases_deterministically():
    """Two full passes must agree; a second run inheriting state would show here."""
    first = {r.case_id: r.outcome for r in run_suite([m4.s4], default_cases())}
    second = {r.case_id: r.outcome for r in run_suite([m4.s4], default_cases())}
    assert first == second, (first, second)
    assert set(first) == {c.id for c in default_cases()}
    for case_id, outcome in first.items():
        assert outcome is not Outcome.ERROR, f"{case_id} errored"


def test_version_metadata_is_reported():
    assert m4.mem0_version() != "unknown"
