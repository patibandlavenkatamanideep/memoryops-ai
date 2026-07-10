"""Recall Gate + Output Gate — audience-aware recall and disclosure control (v1.9, ADR-023).

The Recall Gate keeps sensitive memory out of context for an under-cleared audience;
the Output Gate catches memory-derived disclosure in the generated answer that the
pre-composition gates couldn't see. Both are additive: with the default `private`
audience and an honest (stub) model, behavior is unchanged.
"""

from __future__ import annotations

from app.db.entities import StoredMemory
from app.schemas.memory import ChatRequest, MemoryType, Sensitivity, Source, Status
from app.services.admission_gate import AdmissionDecision, AdmissionRecord
from app.services.output_gate import OutputGate
from app.services.ranker import RankedMemory
from app.services.recall_gate import RecallGate
from app.services.retriever import ScoredCandidate


def _record(sensitivity: Sensitivity, content: str = "secret plan", mem_id: str = "m1") -> AdmissionRecord:
    mem = StoredMemory(
        id=mem_id, tenant_id="t1", user_id="u1", memory_type=MemoryType.semantic,
        content=content, importance=6, confidence=0.9, sensitivity=sensitivity,
        status=Status.active, source=Source(kind="chat"),
    )
    ranked = RankedMemory(
        candidate=ScoredCandidate(memory=mem, semantic=0.8, keyword=0.5),
        score=0.8, score_breakdown={"vector_similarity": 0.8},
    )
    return AdmissionRecord(
        ranked=ranked, decision=AdmissionDecision.ALLOW, reason="ok",
        consent_status="granted", retention_status="none",
    )


# ── Recall Gate ──────────────────────────────────────────────────────────────────
def test_recall_gate_private_allows_all():
    recs = [_record(Sensitivity.high), _record(Sensitivity.medium), _record(Sensitivity.low)]
    result = RecallGate().evaluate(recs, audience="private")
    assert len(result.allowed) == 3 and not result.blocked


def test_recall_gate_public_blocks_medium_and_high():
    recs = [_record(Sensitivity.high, mem_id="h"), _record(Sensitivity.medium, mem_id="m"),
            _record(Sensitivity.low, mem_id="l")]
    result = RecallGate().evaluate(recs, audience="public")
    assert {r.memory.id for r in result.allowed} == {"l"}
    assert {r.memory.id for r in result.blocked} == {"h", "m"}
    assert all(r.decision is AdmissionDecision.BLOCK_AUDIENCE for r in result.blocked)


def test_recall_gate_team_allows_medium_blocks_high():
    recs = [_record(Sensitivity.high, mem_id="h"), _record(Sensitivity.medium, mem_id="m")]
    result = RecallGate().evaluate(recs, audience="team")
    assert {r.memory.id for r in result.allowed} == {"m"}
    assert {r.memory.id for r in result.blocked} == {"h"}


# ── Output Gate ──────────────────────────────────────────────────────────────────
def test_output_gate_allows_when_no_protected_content_leaks():
    protected = [_record(Sensitivity.high, content="the launch date is next tuesday")]
    review = OutputGate().review("Here is a general answer about scheduling.", protected=protected)
    assert review.action == "allow" and review.answer.startswith("Here is a general")


def test_output_gate_redacts_disclosed_phrase():
    protected = [_record(Sensitivity.high, content="the launch date is next tuesday")]
    answer = "Sure — the launch date is next tuesday, don't tell anyone."
    review = OutputGate(mode="redact").review(answer, protected=protected)
    assert review.action == "redacted" and review.escalated
    assert "next tuesday" not in review.answer.lower()
    assert "[redacted]" in review.answer


def test_output_gate_refuse_mode_returns_safe_message():
    protected = [_record(Sensitivity.high, content="the launch date is next tuesday")]
    review = OutputGate(mode="refuse").review("the launch date is next tuesday", protected=protected)
    assert review.action == "refused" and "launch date" not in review.answer.lower()


def test_output_gate_is_noop_without_protected():
    review = OutputGate().review("anything at all here", protected=[])
    assert review.action == "allow"


# ── End-to-end through the gateway ───────────────────────────────────────────────
def _seed(repo, content, sensitivity):
    m = StoredMemory(
        tenant_id="t1", user_id="u1", memory_type=MemoryType.preference,
        content=content, importance=7, confidence=0.9, sensitivity=sensitivity,
        status=Status.active, source=Source(kind="chat", excerpt=content),
        embedding=[1.0, 0.0, 0.0],
    )
    return repo.create_memory(m)


def test_public_audience_blocks_high_sensitivity_from_context(gateway, repo):
    seed = _seed(repo, "my private diagnosis is condition X", Sensitivity.high)
    resp = gateway.handle_chat(
        ChatRequest(tenant_id="t1", user_id="u1", message="what is my diagnosis", audience="public"),
        trace_id="pub",
    )
    # The high-sensitivity memory is recall-blocked for a public audience.
    assert seed.id not in {u.memory_id for u in resp.used_memories}
    blocked = {b.memory_id: b for b in resp.trace.memories_blocked} if resp.trace else {}
    assert blocked.get(seed.id) and blocked[seed.id].admission_decision == "BLOCK_AUDIENCE"


def test_private_audience_is_unchanged(gateway, repo):
    seed = _seed(repo, "my private diagnosis is condition X", Sensitivity.high)
    resp = gateway.handle_chat(
        ChatRequest(tenant_id="t1", user_id="u1", message="what is my diagnosis", audience="private"),
        trace_id="priv",
    )
    # Default private clearance recalls it as before.
    assert seed.id in {u.memory_id for u in resp.used_memories}
    assert resp.output_gate is None  # nothing to redact
