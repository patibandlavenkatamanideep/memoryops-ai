"""Failure-mode / chaos tests (P3.3).

Everything passes on the happy path; these inject real failures and assert the
reliability + deletion invariants hold anyway:

* retrieval blows up mid-request        → the assistant still answers (invariant #4)
* query embedding fails                 → keyword-only fallback, no 500 (#4)
* the LLM provider errors on extraction → heuristic fallback, memory path survives (#4)
* delete-then-read (read-after-delete)  → the deleted memory never surfaces (deletion guarantee)
* every SAVE emits an audit event       → auditability (invariant #7)
"""

from __future__ import annotations

import pytest


def _chat(client, message, tenant="t_chaos", user="u_chaos", **kw):
    body = {"tenant_id": tenant, "user_id": user, "message": message, **kw}
    return client.post("/api/chat", json=body)


def test_retrieval_failure_still_answers(api_client, monkeypatch):
    client, _ = api_client
    import app.services.retriever as retr

    def boom(*a, **k):
        raise RuntimeError("simulated retrieval/DB failure")

    monkeypatch.setattr(retr.Retriever, "retrieve", boom)
    resp = _chat(client, "What do you know about me?")
    assert resp.status_code == 200  # never a 500
    assert resp.json()["retrieval_mode"] in ("none", "fallback")


def test_embedding_failure_degrades_to_fallback(api_client, monkeypatch):
    client, repo = api_client
    _chat(client, "Remember I prefer aisle seats on trains.")
    import app.services.retriever as retr

    def _embed_down(*_a, **_k):
        raise RuntimeError("embed down")

    monkeypatch.setattr(retr, "embed", _embed_down)
    resp = _chat(client, "Which seat do I prefer?")
    assert resp.status_code == 200
    assert resp.json()["retrieval_mode"] == "fallback"


def test_provider_error_on_extraction_falls_back(api_client, monkeypatch):
    client, repo = api_client
    from app.llm.stub_provider import StubProvider

    def boom(*a, **k):
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(StubProvider, "complete", boom)
    # Extraction should degrade to the heuristic and the request must still succeed.
    resp = _chat(client, "Remember I strongly prefer metric units.")
    assert resp.status_code == 200


def test_deleted_memory_never_surfaces_after_delete(api_client):
    client, repo = api_client
    secret = "my locker combination is 24-7-19"
    _chat(client, f"Remember {secret}.")
    mems = repo.list_memories("t_chaos", "u_chaos")
    assert mems, "the memory should have been stored"
    # Delete it, then immediately read back — it must not resurface, directly or in text.
    for m in mems:
        repo.soft_delete("t_chaos", "u_chaos", m.id)
    resp = _chat(client, "What is my locker combination?")
    body = resp.json()
    assert resp.status_code == 200
    assert "24-7-19" not in body["assistant_message"]
    assert all(m.id not in {u.get("memory_id") for u in body.get("used_memories", [])}
               for m in mems)


def test_every_saved_memory_has_an_audit_event(api_client):
    client, repo = api_client
    _chat(client, "Remember I always deploy on Fridays.")
    mems = repo.list_memories("t_chaos", "u_chaos")
    assert mems
    audit = repo.list_audit("t_chaos", user_id="u_chaos")
    audited_ids = {a.memory_id for a in audit}
    # Invariant #7: the write produced an audit event referencing the stored memory.
    assert all(m.id in audited_ids for m in mems)


@pytest.mark.parametrize("n", [5])
def test_repeated_delete_read_is_stable(api_client, n):
    client, repo = api_client
    _chat(client, "Remember my badge number is XZ-9911.")
    mems = repo.list_memories("t_chaos", "u_chaos")
    for m in mems:
        repo.soft_delete("t_chaos", "u_chaos", m.id)
    # Hammer read-after-delete; the deleted content must never leak on any probe.
    for _ in range(n):
        body = _chat(client, "Tell me my badge number.").json()
        assert "XZ-9911" not in body["assistant_message"]
