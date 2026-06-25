"""GET /metrics — Prometheus exposition, content-free + graceful (ADR-015).

Metrics are process-global, so these tests assert presence and *monotonic*
movement (snapshot before/after) rather than exact absolute values.
"""

from __future__ import annotations

import re

import pytest

from app.core.config import get_settings


def _scrape(client) -> str:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    return resp.text


def _sample(text: str, name: str, labels: dict[str, str] | None = None) -> float:
    """Return the value of a metric sample matching name + (subset of) labels.

    Returns 0.0 if no matching sample line is present.
    """
    total = None
    for line in text.splitlines():
        if line.startswith("#") or not line.startswith(name):
            continue
        # Split "name{labels} value" — labels optional.
        m = re.match(rf"^{re.escape(name)}(\{{(?P<labels>[^}}]*)\}})?\s+(?P<val>[\d.eE+-]+)$", line)
        if not m:
            continue
        line_labels = {}
        if m.group("labels"):
            for pair in m.group("labels").split(","):
                k, _, v = pair.partition("=")
                line_labels[k.strip()] = v.strip().strip('"')
        if labels and not all(line_labels.get(k) == v for k, v in labels.items()):
            continue
        total = (total or 0.0) + float(m.group("val"))
    return total if total is not None else 0.0


def _chat(client, message: str, **kw):
    payload = {"tenant_id": "t1", "user_id": "u1", "message": message, **kw}
    return client.post("/api/chat", json=payload)


def test_metrics_endpoint_is_prometheus_text(api_client):
    client, _ = api_client
    text = _scrape(client)
    assert "# TYPE memoryops_http_requests_total counter" in text
    assert "# TYPE memoryops_http_request_duration_ms histogram" in text
    assert "# TYPE memoryops_policy_decisions_total counter" in text


def test_chat_increments_http_and_retrieval_counters(api_client):
    client, _ = api_client
    before = _scrape(client)
    http_before = _sample(before, "memoryops_http_requests_total")
    retr_before = _sample(before, "memoryops_retrieval_total")

    _chat(client, "Remember that I prefer dark mode dashboards.")

    after = _scrape(client)
    assert _sample(after, "memoryops_http_requests_total") > http_before
    assert _sample(after, "memoryops_retrieval_total") > retr_before
    # The chat write recorded at least one policy decision.
    assert _sample(after, "memoryops_policy_decisions_total") > 0


def test_blocked_secret_increments_block_decision(api_client):
    client, _ = api_client
    before = _sample(_scrape(client), "memoryops_policy_decisions_total", {"decision": "BLOCK"})
    _chat(client, "Remember that my API key is sk-test-123456789abcdefghij.")
    after = _sample(_scrape(client), "memoryops_policy_decisions_total", {"decision": "BLOCK"})
    assert after > before


def test_retrieval_fallback_mode_is_recorded(api_client, monkeypatch):
    client, _ = api_client

    def _raise(_text):
        raise RuntimeError("embedding backend unavailable")

    monkeypatch.setattr("app.services.retriever.embed", _raise)

    before = _sample(_scrape(client), "memoryops_retrieval_total", {"mode": "fallback"})
    _chat(client, "What dashboard theme do I like?")
    after = _sample(_scrape(client), "memoryops_retrieval_total", {"mode": "fallback"})
    assert after > before


def test_worker_gauge_degrades_when_history_unavailable(api_client, monkeypatch):
    """Repository/worker-history error must not 500 the scrape (invariant #4)."""
    client, _ = api_client

    def _boom(*_a, **_k):
        raise RuntimeError("worker history unavailable")

    monkeypatch.setattr("app.workers.orchestrator.summarize_runtime_health", _boom)
    text = _scrape(client)  # still 200
    # HTTP metrics still render even though worker gauges were skipped.
    assert "memoryops_http_requests_total" in text


def test_metrics_can_be_disabled(api_client, monkeypatch):
    client, _ = api_client
    monkeypatch.setenv("MEMORYOPS_METRICS_ENABLED", "0")
    get_settings.cache_clear()
    try:
        resp = client.get("/metrics")
        assert resp.status_code == 404
        # The rest of the app is unaffected.
        assert client.get("/healthz").status_code == 200
    finally:
        get_settings.cache_clear()


def test_healthz_reports_uptime_and_metrics_flag(api_client):
    client, _ = api_client
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert "uptime_seconds" in body
    assert body["metrics_enabled"] is True


@pytest.mark.parametrize("path", ["/metrics", "/healthz"])
def test_ops_endpoints_emit_no_tenant_labels(api_client, path):
    """Content-free guarantee: no tenant/user identifiers leak into metrics."""
    client, _ = api_client
    _chat(client, "Remember I work at tenant t1 as user u1.")
    text = _scrape(client)
    assert "tenant_id" not in text
    assert "user_id" not in text
