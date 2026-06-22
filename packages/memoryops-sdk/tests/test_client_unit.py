"""Unit contract tests — SDK request shaping + response parsing + error mapping.

Uses httpx.MockTransport so no server is needed. Asserts the SDK injects the
tenant/user scope, hits the right paths, parses responses into typed models, and
maps HTTP errors to typed exceptions.
"""

from __future__ import annotations

import json

import httpx
import pytest

from memoryops import LegalHoldError, MemoryOpsClient, NotFoundError


def _client(handler) -> MemoryOpsClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://test")
    return MemoryOpsClient("http://test", "t1", "u1", http_client=http)


def test_chat_injects_scope_and_parses_result() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "assistant_message": "ok",
            "used_memories": [{"memory_id": "m1", "content": "likes tea", "score": 0.9}],
            "candidate_memories": [{"content": "likes tea", "decision": "SAVE"}],
            "retrieval_mode": "hybrid",
            "trace_id": "tr1",
            "temporary_chat": False,
        })

    with _client(handler) as mo:
        result = mo.chat("hi there", temporary_chat=False)

    assert seen["url"].endswith("/api/chat")
    assert seen["body"]["tenant_id"] == "t1" and seen["body"]["user_id"] == "u1"
    assert seen["body"]["message"] == "hi there"
    assert result.assistant_message == "ok"
    assert result.retrieval_mode == "hybrid"
    assert result.used_memories[0].content == "likes tea"
    assert result.candidate_memories[0].decision == "SAVE"


def test_list_memories_passes_scope_as_query() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=[
            {"id": "m1", "content": "x", "memory_type": "preference", "status": "active",
             "importance": 5, "confidence": 0.8, "sensitivity": "low"},
        ])

    with _client(handler) as mo:
        mems = mo.list_memories(status="active")

    assert seen["params"]["tenant_id"] == "t1"
    assert seen["params"]["user_id"] == "u1"
    assert seen["params"]["status"] == "active"
    assert mems[0].id == "m1" and mems[0].memory_type == "preference"


def test_delete_under_legal_hold_raises_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "memory is under legal hold"})

    with _client(handler) as mo:
        with pytest.raises(LegalHoldError) as exc:
            mo.delete_memory("m1")
    assert exc.value.status_code == 409
    assert "legal hold" in (exc.value.detail or "")


def test_missing_memory_raises_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "memory not found"})

    with _client(handler) as mo:
        with pytest.raises(NotFoundError):
            mo.get_memory("nope")


def test_set_legal_hold_builds_body() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"memory_id": "m1", "governance": {"legal_hold": True}})

    with _client(handler) as mo:
        out = mo.set_legal_hold("m1", on=True, reason="litigation")

    assert seen["url"].endswith("/api/retention/legal-hold")
    assert seen["body"] == {"tenant_id": "t1", "user_id": "u1", "memory_id": "m1",
                            "on": True, "reason": "litigation"}
    assert out["governance"]["legal_hold"] is True


def test_retention_decisions_parses_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "policy": "default", "scanned": 1, "summary": {"expired": 1},
            "decisions": [{"memory_id": "m1", "policy": "default", "outcome": "expired",
                           "eligible_for_deletion": True, "blocked_by": [], "reason": "old"}],
        })

    with _client(handler) as mo:
        decisions = mo.retention_decisions(policy="default")
    assert decisions[0].outcome == "expired"
    assert decisions[0].eligible_for_deletion is True


def test_generic_api_error_surfaces_status() -> None:
    from memoryops import APIError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with _client(handler) as mo:
        with pytest.raises(APIError) as exc:
            mo.metrics()
    assert exc.value.status_code == 500
