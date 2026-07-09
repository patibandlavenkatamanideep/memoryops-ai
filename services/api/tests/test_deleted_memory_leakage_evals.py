"""Deleted / expired memory leakage evals (v1.5, ADR-019).

Extends the v1.4 leakage suite (ADR-018) with a poison-memory battery and three
new proofs that deleted or expired memory can never influence output:

  * ``cross_session_leakage`` — a deleted memory does not leak into a brand-new
    session (a fresh stack rebuilt on the same store; also proves reindex/rebuild
    non-reappearance).
  * ``expiry_leakage`` — a retention-expired / consent-withdrawn *active* memory is
    denied context admission without being deleted.
  * ``derived_tombstone`` with ``chain_depth`` — lineage blocking is transitive
    through a multi-level derivation chain, not just one hop.

Each eval carries its own teeth: it first asserts the secret WAS used (``used_before``)
before deletion/expiry, so a pass can never be vacuous. The tests below re-assert that
teeth directly and check the admission *decision*, not just the used-memory list.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db import governance as gov
from app.db import lineage
from app.db.entities import StoredMemory
from app.db.memory_repo import InMemoryRepository
from app.schemas.memory import (
    ChatRequest,
    MemoryType,
    Sensitivity,
    Source,
    Status,
)
from app.services.eval_harness import run_evals
from app.services.gateway import Gateway


def _chat(gw: Gateway, message: str, *, tenant="t1", user="u1", temporary=False):
    return gw.handle_chat(
        ChatRequest(tenant_id=tenant, user_id=user, message=message, temporary_chat=temporary),
        trace_id="test",
    )


def _used_ids(resp) -> set[str]:
    return {u.memory_id for u in resp.used_memories}


def _used_text(resp) -> str:
    return " ".join(u.content.lower() for u in resp.used_memories)


# ── the eval suite itself passes end-to-end ─────────────────────────────────────
_NEW_KINDS = {"leakage", "cross_session_leakage", "expiry_leakage", "derived_tombstone"}


def test_all_leakage_kind_cases_pass():
    """Every leakage-family adversarial case passes (poison battery included)."""
    report = run_evals()
    leakage_results = [r for r in report.results if r.kind in _NEW_KINDS]
    assert leakage_results, "expected leakage-family cases to be present"
    failed = [(r.id, r.detail) for r in leakage_results if not r.passed]
    assert not failed, f"leakage cases failed: {failed}"


def test_new_kinds_are_actually_exercised():
    """The v1.5 kinds are present in the suite (guards against silent removal)."""
    report = run_evals()
    kinds = {r.kind for r in report.results}
    assert {"cross_session_leakage", "expiry_leakage"} <= kinds


# ── cross-session leakage: fresh session must not see a deleted memory ───────────
def test_cross_session_delete_does_not_leak_but_had_teeth():
    repo = InMemoryRepository()
    gw = Gateway(repo)
    _chat(gw, "Remember that I prefer Vendor X for all cloud deployments.")
    row = repo.list_memories("t1", "u1")[0]

    # Teeth: before deletion the memory IS used for the probe.
    before = _chat(gw, "Which vendor do I usually prefer?")
    assert row.id in _used_ids(before), "baseline must use the memory or the test is vacuous"
    assert "vendor x" in _used_text(before)

    repo.soft_delete("t1", "u1", row.id)

    # A brand-new session (fresh Gateway) rebuilds the whole read stack.
    fresh = Gateway(repo)
    for q in ("Which vendor do I usually prefer?",
              "Based on my past choices, what cloud vendor should I pick?"):
        resp = _chat(fresh, q)
        assert row.id not in _used_ids(resp)
        assert "vendor x" not in _used_text(resp)
        assert "vendor x" not in resp.assistant_message.lower()

    assert row.id not in {m.id for m in repo.retrieve_active("t1", "u1")}


# ── expiry leakage: expired / consent-withdrawn active memory is gated out ───────
def test_retention_expired_memory_is_denied_admission_not_deleted():
    repo = InMemoryRepository()
    gw = Gateway(repo)
    _chat(gw, "Remember that I prefer Vendor X for all cloud deployments.")
    row = repo.list_memories("t1", "u1")[0]

    before = _chat(gw, "Which vendor do I usually prefer?")
    assert row.id in _used_ids(before)  # teeth

    gov.set_retention(row, policy="eval-expired", expires_at=datetime.now(UTC) - timedelta(days=1))
    repo.update_memory(row)

    resp = _chat(gw, "Which vendor do I usually prefer?")
    assert row.id not in _used_ids(resp)
    assert "vendor x" not in resp.assistant_message.lower()
    # Expiry is not deletion — the row is still active, just gated out of context.
    assert row.id in {m.id for m in repo.retrieve_active("t1", "u1")}
    # And the trace explains WHY: blocked as expired.
    blocked = {b.memory_id: b for b in resp.trace.memories_blocked} if resp.trace else {}
    assert row.id in blocked
    assert blocked[row.id].admission_decision == "BLOCK_EXPIRED"


def test_consent_withdrawn_memory_is_denied_admission():
    repo = InMemoryRepository()
    gw = Gateway(repo)
    _chat(gw, "Remember that I am allergic to penicillin.")
    row = repo.list_memories("t1", "u1")[0]

    before = _chat(gw, "What am I allergic to?")
    assert row.id in _used_ids(before)  # teeth

    gov.set_consent(row, status=gov.ConsentStatus.withdrawn)
    repo.update_memory(row)

    resp = _chat(gw, "What am I allergic to?")
    assert row.id not in _used_ids(resp)
    assert "penicillin" not in resp.assistant_message.lower()
    blocked = {b.memory_id: b for b in resp.trace.memories_blocked} if resp.trace else {}
    assert blocked.get(row.id) and blocked[row.id].admission_decision == "BLOCK_CONSENT_WITHDRAWN"


# ── transitive lineage: a deleted root blocks a multi-hop descendant ─────────────
def test_deleting_root_blocks_grandchild_artifact():
    repo = InMemoryRepository()
    gw = Gateway(repo)
    _chat(gw, "Remember that I prefer Vendor X for all cloud deployments.")
    root = repo.list_memories("t1", "u1")[0]

    # root → middle → leaf (grandchild summary that carries the secret)
    middle = StoredMemory(
        tenant_id="t1", user_id="u1", memory_type=MemoryType.semantic,
        content="Intermediate consolidation of an earlier memory.",
        importance=6, confidence=0.9, sensitivity=Sensitivity.low,
        status=Status.active, source=Source(kind="reflection"),
    )
    lineage.set_lineage(middle, parent_ids=[root.id])
    repo.create_memory(middle)
    leaf = StoredMemory(
        tenant_id="t1", user_id="u1", memory_type=MemoryType.semantic,
        content="Summary: the user consistently chooses Vendor X for cloud workloads.",
        importance=6, confidence=0.9, sensitivity=Sensitivity.low,
        status=Status.active, source=Source(kind="reflection"),
    )
    lineage.set_lineage(leaf, parent_ids=[middle.id])
    repo.create_memory(leaf)

    before = _chat(gw, "Which cloud vendor do I prefer?")
    assert leaf.id in _used_ids(before)  # teeth: the grandchild is used

    repo.soft_delete("t1", "u1", root.id)
    lineage.set_tombstone(root, on=True, reason="deleted")
    repo.update_memory(root)

    resp = _chat(gw, "Which cloud vendor do I prefer?")
    assert leaf.id not in _used_ids(resp), "grandchild of a deleted root must be blocked"
    assert "vendor x" not in resp.assistant_message.lower()
