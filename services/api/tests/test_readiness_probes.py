"""Dependency-specific readiness probe (v2.3).

``GET /readyz`` reports one ``{"status": ok|skipped|error}`` per backing
dependency instead of a single combined string, never raises, and never leaks
credentials, DSNs, API keys, or raw exception text.
"""

from __future__ import annotations

import json

_DEPENDENCIES = (
    "storage",
    "schema",
    "vector_backend",
    "worker_runtime",
    "llm_provider",
    "embedding_provider",
)


def test_readyz_reports_per_dependency_states(api_client):
    client, _repo = api_client
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert body["profile"] == "dev"
    checks = body["checks"]
    for name in _DEPENDENCIES:
        assert name in checks, name
        assert checks[name]["status"] in ("ok", "skipped", "error")
    # In-memory dev store: schema + worker runtime are not applicable → skipped,
    # not error (an unselected/optional dependency must never block readiness).
    assert checks["schema"]["status"] == "skipped"
    assert checks["worker_runtime"]["status"] == "skipped"
    assert checks["storage"]["status"] == "ok"


def test_readyz_error_in_a_required_dependency_sets_not_ready(api_client, monkeypatch):
    """If a required dependency probe fails, ready=false — but the endpoint still
    returns 200 with a structured body (no-throw)."""
    client, _repo = api_client
    from app.routes import health

    def _boom(_settings):
        return {"status": "error", "backend": "postgres", "detail": "OperationalError"}

    monkeypatch.setattr(health, "_check_storage", _boom)
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False
    assert body["checks"]["storage"]["status"] == "error"


def test_readyz_never_leaks_secrets(api_client, monkeypatch):
    """Even when a probe fails with a secret-bearing exception, the response must
    carry only the exception *type*, never its message/DSN/credentials."""
    client, _repo = api_client
    from app.routes import health

    secret_dsn = "postgresql+psycopg://admin:SUP3RSECRET@db.internal:5432/prod"

    def _raises(*_a, **_k):
        raise RuntimeError(f"could not connect to {secret_dsn} apikey=sk-DEADBEEF")

    # Force the real _check_storage to hit a raising repository probe.
    monkeypatch.setattr(health, "get_repository", _raises)
    r = client.get("/readyz")
    assert r.status_code == 200
    blob = json.dumps(r.json())
    for secret in ("SUP3RSECRET", "sk-DEADBEEF", secret_dsn, "admin:"):
        assert secret not in blob
    # The failing dependency is still reported as an error, by type only.
    assert r.json()["checks"]["storage"]["status"] == "error"
    assert r.json()["checks"]["storage"]["detail"] == "RuntimeError"
