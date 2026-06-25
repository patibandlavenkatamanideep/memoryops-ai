"""Advisory economics: token + cost estimation (v1.2, ADR-016).

Estimates are deterministic and work offline. Costs are advisory: unknown/stub
models are unpriced ($0); priced models use the default table or an env override.
"""

from __future__ import annotations

import re

from app.economics import build_request_economics, estimate_cost_usd, price_per_1m


def _chat(client, message: str, **kw):
    return client.post(
        "/api/chat", json={"tenant_id": "t1", "user_id": "u1", "message": message, **kw}
    )


# ── pricing + estimator (pure) ─────────────────────────────────────────────────


def test_stub_and_unknown_models_are_unpriced():
    assert price_per_1m("") is None
    assert price_per_1m("some-unknown-model") is None
    assert estimate_cost_usd("", 1000, kind="input") == 0.0
    assert estimate_cost_usd("some-unknown-model", 1000, kind="embedding") == 0.0


def test_known_model_is_priced():
    # text-embedding-3-small default = $0.02 / 1M tokens.
    assert estimate_cost_usd("text-embedding-3-small", 1_000_000, kind="embedding") == 0.02
    # gpt-4o-mini default input = $0.15 / 1M.
    assert estimate_cost_usd("gpt-4o-mini", 1_000_000, kind="input") == 0.15


def test_env_override_takes_precedence():
    override = '{"gpt-4o-mini": {"input": 1.0}}'
    assert estimate_cost_usd("gpt-4o-mini", 1_000_000, kind="input", overrides_json=override) == 1.0


def test_malformed_override_is_ignored():
    # Falls back to the default table rather than raising.
    assert (
        estimate_cost_usd("gpt-4o-mini", 1_000_000, kind="input", overrides_json="not json")
        == 0.15
    )


def test_build_request_economics_values_and_savings():
    econ = build_request_economics(
        embedding_model="text-embedding-3-small",
        llm_model="gpt-4o-mini",
        query_text="x" * 40,  # ~10 tokens
        context_tokens=100,
        compressed_tokens=60,
        tokens_saved=40,
        llm_context_text="y" * 400,  # ~100 tokens
        embedded=True,
        overrides_json="",
    )
    assert econ.priced is True
    assert econ.embedding_tokens == 10
    assert econ.llm_input_tokens == 110  # 100 context + 10 query
    assert econ.estimated_cost_usd > 0
    assert econ.cost_saved_usd > 0  # 40 saved tokens valued at the input rate


def test_unpriced_keeps_tokens_zero_cost():
    econ = build_request_economics(
        embedding_model="",  # stub
        llm_model="",  # stub
        query_text="hello there",
        context_tokens=50,
        compressed_tokens=50,
        tokens_saved=0,
        llm_context_text="some composed context block",
        embedded=True,
        overrides_json="",
    )
    assert econ.priced is False
    assert econ.estimated_cost_usd == 0.0
    assert econ.llm_input_tokens > 0  # tokens still tracked


# ── end-to-end through the chat path ───────────────────────────────────────────


def test_chat_response_carries_economics_block(api_client):
    client, _ = api_client
    _chat(client, "Remember that I prefer dark mode dashboards.")
    resp = _chat(client, "Which theme do I like?")
    body = resp.json()
    econ = body["economics"]
    assert econ is not None
    assert econ["llm_input_tokens"] >= 0
    # Default stub providers ⇒ unpriced ⇒ zero cost but real token counts.
    assert econ["priced"] is False
    assert econ["estimated_cost_usd"] == 0.0


def _sample(text: str, name: str, labels: dict[str, str] | None = None) -> float:
    total = None
    for line in text.splitlines():
        if line.startswith("#") or not line.startswith(name):
            continue
        pattern = rf"^{re.escape(name)}(\{{(?P<labels>[^}}]*)\}})?\s+(?P<val>[\d.eE+-]+)$"
        mm = re.match(pattern, line)
        if not mm:
            continue
        line_labels = {}
        if mm.group("labels"):
            for pair in mm.group("labels").split(","):
                k, _, v = pair.partition("=")
                line_labels[k.strip()] = v.strip().strip('"')
        if labels and not all(line_labels.get(k) == v for k, v in labels.items()):
            continue
        total = (total or 0.0) + float(mm.group("val"))
    return total if total is not None else 0.0


def test_metrics_expose_token_counters_without_pii(api_client):
    client, _ = api_client
    before = _sample(client.get("/metrics").text, "memoryops_tokens_total")
    _chat(client, "Remember that I prefer dark mode dashboards and concise summaries.")
    text = client.get("/metrics").text
    assert "# TYPE memoryops_tokens_total counter" in text
    assert "# TYPE memoryops_estimated_cost_usd_total counter" in text
    assert _sample(text, "memoryops_tokens_total") > before
    # Content-free: no tenant/user labels leak into economics metrics.
    assert "tenant_id" not in text
    assert "user_id" not in text


def test_economics_failure_is_non_fatal(api_client, monkeypatch):
    """If estimation raises, the chat still succeeds (invariant #4)."""
    client, _ = api_client

    def _boom(*_a, **_k):
        raise RuntimeError("estimator exploded")

    monkeypatch.setattr("app.services.gateway.build_request_economics", _boom)
    resp = _chat(client, "Remember that I like dark mode.")
    assert resp.status_code == 200
    assert resp.json()["economics"] is None  # skipped, but chat unaffected
