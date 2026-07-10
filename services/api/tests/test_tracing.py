"""Distributed tracing façade + lifecycle instrumentation (v1.8, ADR-022).

Proves spans are recorded with correlation ids and parent/child nesting, that the
lifecycle (read/write/worker) is instrumented, that recording is no-throw and
content-free, and that `GET /api/traces` exposes the correlated view.
"""

from __future__ import annotations

import pytest

from app.observability import (
    current_correlation_id,
    new_correlation_id,
    recent_spans,
    reset_spans,
    set_correlation_id,
    span,
)


@pytest.fixture(autouse=True)
def _clean_spans():
    reset_spans()
    set_correlation_id("test-corr")
    yield
    reset_spans()


def test_span_records_with_correlation_and_duration():
    with span("unit.op", count=3):
        pass
    spans = recent_spans()
    assert spans and spans[0]["name"] == "unit.op"
    assert spans[0]["correlation_id"] == "test-corr"
    assert spans[0]["attributes"] == {"count": 3}
    assert spans[0]["duration_ms"] is not None
    assert spans[0]["status"] == "ok"


def test_span_nesting_sets_parent():
    with span("parent"):
        with span("child"):
            pass
    spans = {s["name"]: s for s in recent_spans()}
    assert spans["child"]["parent_span_id"] == spans["parent"]["span_id"]
    assert spans["parent"]["parent_span_id"] is None


def test_span_records_error_status_and_reraises():
    with pytest.raises(ValueError):
        with span("boom"):
            raise ValueError("x")
    assert recent_spans()[0]["status"] == "error"


def test_span_is_content_free_only_passed_attributes():
    with span("op", mode="hybrid", secret=None):
        pass
    attrs = recent_spans()[0]["attributes"]
    assert attrs == {"mode": "hybrid"}  # None dropped; nothing else injected


def test_new_correlation_id_sets_context():
    cid = new_correlation_id("worker")
    assert cid.startswith("worker-") and current_correlation_id() == cid


def test_tracing_disabled_is_noop(monkeypatch):
    from app.core import config

    monkeypatch.setenv("MEMORYOPS_TRACING_ENABLED", "false")
    config.get_settings.cache_clear()
    try:
        with span("should-not-record") as sp:
            assert sp is None
        assert recent_spans() == []
    finally:
        monkeypatch.delenv("MEMORYOPS_TRACING_ENABLED", raising=False)
        config.get_settings.cache_clear()


# ── lifecycle instrumentation ────────────────────────────────────────────────────
def test_chat_turn_emits_read_and_write_spans(gateway):
    from app.schemas.memory import ChatRequest

    reset_spans()
    gateway.handle_chat(
        ChatRequest(tenant_id="t1", user_id="u1", message="Remember I prefer dark mode."),
        trace_id="turn-1",
    )
    names = {s["name"] for s in recent_spans(limit=512)}
    assert {"memory.read", "retrieve", "rank", "admission", "compose"} <= names
    assert "memory.write.extract" in names
    # All spans share the turn's correlation id.
    assert all(s["correlation_id"] == "turn-1" for s in recent_spans(limit=512))


def test_worker_run_emits_job_spans(repo):
    from app.workers.runner import run_jobs

    reset_spans()
    run_jobs(repo, tenant_id="t1", user_id="u1", jobs=["decay"], dry_run=True)
    job_spans = [s for s in recent_spans(limit=512) if s["name"] == "worker.job"]
    assert job_spans and job_spans[0]["attributes"].get("job") == "decay"
    assert job_spans[0]["correlation_id"].startswith("worker-")


# ── endpoint ─────────────────────────────────────────────────────────────────────
def test_traces_endpoint_returns_spans(api_client):
    client, _ = api_client
    reset_spans()
    client.post("/api/chat", json={"tenant_id": "t1", "user_id": "u1", "message": "hi there"})
    r = client.get("/api/traces?limit=50")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert any(s["name"] == "memory.read" for s in body["spans"])


def test_traces_endpoint_filters_by_correlation(api_client):
    client, _ = api_client
    reset_spans()
    client.post(
        "/api/chat",
        json={"tenant_id": "t1", "user_id": "u1", "message": "hello"},
        headers={"x-trace-id": "corr-abc"},
    )
    r = client.get("/api/traces?correlation_id=corr-abc")
    spans = r.json()["spans"]
    assert spans and all(s["correlation_id"] == "corr-abc" for s in spans)
