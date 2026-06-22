"""Test fixtures for the MemoryOps SDK.

Two ways to drive the client without a network:
  * ``mock_client`` — an httpx.MockTransport with canned JSON, for fast,
    self-contained contract tests of request shaping + response parsing.
  * ``live_client`` — the SDK bound in-process to the real FastAPI app via
    httpx.ASGITransport, proving the SDK matches the live API contract. Skipped
    automatically if the API package isn't importable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from memoryops import MemoryOpsClient

# Make the API package importable for the in-process end-to-end fixture.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_API_DIR = _REPO_ROOT / "services" / "api"
if _API_DIR.is_dir() and str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))


@pytest.fixture
def live_client():
    """SDK bound to the real ASGI app with a fresh in-memory repo per test."""
    import os

    os.environ["MEMORYOPS_STORAGE"] = "memory"
    pytest.importorskip("fastapi")
    try:
        from app import deps  # type: ignore
        from app.db import factory  # type: ignore
        from app.main import app  # type: ignore
    except Exception:  # noqa: BLE001 — API package not available in this checkout
        pytest.skip("MemoryOps API package not importable")

    from fastapi.testclient import TestClient

    factory.get_repository.cache_clear()
    deps.gateway.cache_clear()
    deps.audit_service.cache_clear()

    # TestClient is a sync httpx.Client that bridges to the ASGI app — pass it
    # straight to the SDK so the client exercises the real route handlers.
    http = TestClient(app)
    client = MemoryOpsClient(
        "http://testserver", tenant_id="tenant_demo", user_id="user_demo", http_client=http
    )
    yield client
    client.close()
    factory.get_repository.cache_clear()
    deps.gateway.cache_clear()
    deps.audit_service.cache_clear()
