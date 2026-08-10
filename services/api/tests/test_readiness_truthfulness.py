"""Readiness must report what a dependency *can do*, not what it was *named*.

`/readyz` previously derived `llm_provider` and `embedding_provider` status purely
from the configured provider name — both were hardcoded `{"status": "ok"}`. An
operator who set `MEMORYOPS_LLM_PROVIDER=openai` with no key and no SDK installed
saw a fully green probe while every request was served by the deterministic stub.
`vector_backend` was the same: any external backend reported `ok` with a note that
it "degrades to keyword-only if unreachable", so a misconfigured Qdrant URL — or a
missing client library — looked healthy while all ranking silently fell back.

Severity is profile-aware: in production a selected-but-unusable provider is an
`error` (the deployment asked for it); in dev it is `degraded` (the fallback is the
intended offline experience). No probe may leak a key, DSN, or raw provider error.
"""

from __future__ import annotations

import json

import pytest

from app.routes import health


@pytest.fixture
def no_sdks(monkeypatch):
    """Simulate an image with none of the optional provider SDKs installed."""
    monkeypatch.setattr(health, "_module_missing", lambda module: True)


@pytest.fixture
def all_sdks(monkeypatch):
    monkeypatch.setattr(health, "_module_missing", lambda module: False)


def _settings(**overrides):
    from app.core.config import Settings

    base = dict(profile="dev", storage="memory")
    return Settings(**{**base, **overrides})


# ── LLM provider ─────────────────────────────────────────────────────────────
def test_stub_llm_provider_is_ok_without_any_sdk(no_sdks):
    assert health._check_llm_provider(_settings(llm_provider="stub"))["status"] == "ok"


def test_selected_llm_provider_without_key_is_not_reported_ok(all_sdks):
    check = health._check_llm_provider(_settings(llm_provider="openai", openai_api_key=""))
    assert check["status"] == "degraded"
    assert check["reason_code"] == "missing_api_key"
    assert check["fallback"] == "stub"


def test_selected_llm_provider_without_sdk_is_not_reported_ok(no_sdks):
    check = health._check_llm_provider(
        _settings(llm_provider="anthropic", anthropic_api_key="sk-real")
    )
    assert check["status"] == "degraded"
    assert check["reason_code"] == "sdk_not_installed"
    assert check["install_extra"] == "anthropic"


def test_unusable_provider_is_an_error_in_production(all_sdks):
    check = health._check_llm_provider(
        _settings(profile="production", llm_provider="openai", openai_api_key="")
    )
    assert check["status"] == "error", "production asked for a real provider; say so"


def test_fully_configured_llm_provider_is_ok(all_sdks):
    check = health._check_llm_provider(
        _settings(llm_provider="openai", openai_api_key="sk-real")
    )
    assert check["status"] == "ok"
    # Configuration is verified; liveness deliberately is not (a probe must not
    # spend tokens or hit a rate limit on every scrape).
    assert check["liveness"] == "not_probed"


def test_gemini_probe_uses_the_module_the_adapter_imports(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(health, "_module_missing", lambda m: seen.append(m) or False)
    health._check_llm_provider(_settings(llm_provider="gemini", gemini_api_key="k"))
    assert seen == ["google.genai"]


# ── embedding provider ───────────────────────────────────────────────────────
def test_openai_embeddings_without_key_is_not_reported_ok(all_sdks):
    check = health._check_embedding_provider(
        _settings(embeddings_provider="openai", openai_api_key="")
    )
    assert check["status"] == "degraded"
    assert check["reason_code"] == "missing_api_key"


def test_stub_embeddings_are_ok(no_sdks):
    assert health._check_embedding_provider(_settings())["status"] == "ok"


# ── vector backend ───────────────────────────────────────────────────────────
def test_memory_vector_backend_is_ok(no_sdks):
    assert health._check_vector_backend(_settings(vector_index="memory"))["status"] == "ok"


def test_external_vector_backend_without_client_is_not_reported_ok(no_sdks):
    check = health._check_vector_backend(_settings(vector_index="qdrant"))
    assert check["status"] == "degraded"
    assert check["reason_code"] == "client_not_installed"
    assert check["fallback"] == "keyword_only"


def test_unreachable_vector_backend_is_not_reported_ok(all_sdks, monkeypatch):
    """The real regression: a selected-but-unreachable index used to report ok."""

    class _Unavailable:
        def available(self) -> bool:
            return False

    monkeypatch.setattr(
        "app.db.vector.factory.create_vector_index", lambda name, **kw: _Unavailable()
    )
    check = health._check_vector_backend(_settings(vector_index="qdrant"))
    assert check["status"] == "degraded"
    assert check["reason_code"] == "backend_unreachable"


def test_vector_backend_probe_never_raises(all_sdks, monkeypatch):
    def _boom(name, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("app.db.vector.factory.create_vector_index", _boom)
    check = health._check_vector_backend(_settings(vector_index="weaviate"))
    assert check["status"] == "degraded"
    assert check["reason_code"] == "probe_failed"


# ── worker freshness ─────────────────────────────────────────────────────────
def test_worker_staleness_is_none_when_nothing_has_run():
    assert health._worker_staleness_seconds({"last_run_per_scope": {}}) is None


def test_worker_staleness_uses_the_most_recent_run():
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    summary = {
        "last_run_per_scope": {
            "t1:u1": {"started_at": (now - timedelta(seconds=600)).isoformat()},
            "t2:u2": {"started_at": (now - timedelta(seconds=30)).isoformat()},
        }
    }
    age = health._worker_staleness_seconds(summary)
    assert age is not None and age < 60, "must use the newest run, not the oldest"


def test_worker_staleness_tolerates_malformed_timestamps():
    assert health._worker_staleness_seconds(
        {"last_run_per_scope": {"t:u": {"started_at": "not-a-date"}}}
    ) is None


# ── response shape + secret hygiene ──────────────────────────────────────────
def test_readyz_exposes_a_degraded_flag(api_client):
    client, _repo = api_client
    body = client.get("/readyz").json()
    assert "degraded" in body
    assert isinstance(body["degraded"], bool)


def test_readyz_never_leaks_secrets_even_when_degraded(api_client, monkeypatch):
    client, _repo = api_client
    monkeypatch.setattr(health, "_module_missing", lambda m: True)
    blob = json.dumps(client.get("/readyz").json())
    for secret in ("sk-", "postgresql://", "postgresql+psycopg://", "password", "@localhost"):
        assert secret not in blob, f"readiness leaked {secret!r}"


def test_readyz_never_raises_even_if_a_probe_explodes(api_client, monkeypatch):
    """Readiness is what an operator hits when things are broken — it must not 500."""

    def _boom(_settings):
        raise RuntimeError("connection string postgresql://user:hunter2@db/x is bad")

    monkeypatch.setattr(health, "_check_storage", _boom)
    client, _repo = api_client
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False
    assert body["checks"]["storage"]["status"] == "error"
    assert body["checks"]["storage"]["reason_code"] == "probe_raised"
    # Only the exception type, never its message (which carried a DSN + password).
    assert "hunter2" not in json.dumps(body)
    assert body["checks"]["storage"]["detail"] == "RuntimeError"
