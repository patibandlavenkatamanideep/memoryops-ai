from __future__ import annotations

from app.loops.types import LoopId, LoopStatus
from app.observability import registry as m
from app.schemas.memory import ChatRequest


def _chat(gateway, message, trace_id="trace-read"):
    return gateway.handle_chat(
        ChatRequest(tenant_id="t1", user_id="u1", message=message), trace_id=trace_id
    )


def _counter_total(counter) -> float:
    return sum(v for _labels, v in counter.samples())


def test_memory_path_records_metrics(gateway):
    """The gateway read/write path records Prometheus metrics (ADR-015) without
    altering loop behavior — retrieval + policy-decision counters move."""
    retr_before = _counter_total(m.RETRIEVAL_TOTAL)
    policy_before = _counter_total(m.POLICY_DECISIONS_TOTAL)
    _chat(gateway, "Remember that I prefer dark mode dashboards.", trace_id="metrics")
    assert _counter_total(m.RETRIEVAL_TOTAL) > retr_before
    assert _counter_total(m.POLICY_DECISIONS_TOTAL) > policy_before


def test_read_path_emits_tracing_spans(gateway):
    """v1.8: the read path is traced (memory.read → retrieve/rank/admission/compose)
    under this turn's correlation id, without altering loop/metrics behavior."""
    from app.observability import recent_spans, reset_spans

    reset_spans()
    _chat(gateway, "Remember that I prefer dark mode dashboards.", trace_id="trace-spans")
    names = {s["name"] for s in recent_spans(limit=512)}
    assert {"memory.read", "retrieve", "rank", "admission", "compose"} <= names
    assert all(
        s["correlation_id"] == "trace-spans"
        for s in recent_spans(limit=512)
        if s["name"] == "memory.read"
    )


def test_memory_path_attaches_economics(gateway):
    """The read path attaches an advisory economics estimate (ADR-016) without
    altering loop behavior; token counters move and cost is 0 under stub providers."""
    tokens_before = _counter_total(m.TOKENS_TOTAL)
    resp = _chat(gateway, "Remember that I prefer dark mode dashboards.", trace_id="econ")
    assert resp.economics is not None
    assert resp.economics.llm_input_tokens >= 0
    assert resp.economics.priced is False  # stub providers ⇒ unpriced
    assert _counter_total(m.TOKENS_TOTAL) > tokens_before


def test_memory_read_loop_emits_events(gateway, repo):
    _chat(gateway, "Remember that I prefer dark mode dashboards.", trace_id="seed")
    resp = _chat(gateway, "Which dashboard theme do I like?")
    runs = repo.list_loop_runs(loop_id=LoopId.MEMORY_READ.value, trace_id="trace-read")
    assert runs
    assert runs[0].status == LoopStatus.COMPLETED
    assert resp.loop_evidence[LoopId.MEMORY_READ.value] == "completed"
    assert repo.list_loop_events(loop_run_id=runs[0].id, event_type="memory_read_completed")


def test_safe_degraded_loop_is_not_failure(gateway, repo, monkeypatch):
    _chat(gateway, "Remember that I prefer dark mode dashboards.", trace_id="seed")

    def _raise(_text):
        raise RuntimeError("embedding backend unavailable")

    monkeypatch.setattr("app.services.retriever.embed", _raise)
    resp = _chat(gateway, "Which dashboard theme do I like?", trace_id="trace-fallback")
    runs = repo.list_loop_runs(loop_id=LoopId.MEMORY_READ.value, trace_id="trace-fallback")
    assert runs[0].status == LoopStatus.SAFE_DEGRADED
    assert runs[0].status != LoopStatus.FAILED
    assert resp.loop_evidence[LoopId.MEMORY_READ.value] == "safe_degraded"
