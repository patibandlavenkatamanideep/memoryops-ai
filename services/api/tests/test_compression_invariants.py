"""Compression must not weaken MemoryOps invariants (v0.2.1).

Deleted / wrong-tenant memories are never retrieved, so they are never composed
and therefore never compressed. Temporary chat composes nothing. The policy
broker always sees the raw message because compression touches only the read-side
context block, not the write path.
"""

from __future__ import annotations

from app.compression.headroom_adapter import HeadroomCompressor
from app.schemas.memory import ChatRequest, Decision


def _chat(gateway, message, tenant="t1", user="u1", **kw):
    return gateway.handle_chat(
        ChatRequest(tenant_id=tenant, user_id=user, message=message, **kw), trace_id="test"
    )


def _spy_gateway(gateway):
    seen: list[str] = []
    gateway._compressor = HeadroomCompressor(engine=lambda t: seen.append(t) or t)
    return seen


def test_deleted_memory_not_compressed(gateway, repo):
    seen = _spy_gateway(gateway)
    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    mem = repo.list_memories("t1", "u1")[0]
    repo.soft_delete("t1", "u1", mem.id)
    seen.clear()
    resp = _chat(gateway, "Which dashboard theme do I like?")
    assert all(u.memory_id != mem.id for u in resp.used_memories)
    assert all("dark mode" not in s.lower() for s in seen)


def test_wrong_tenant_memory_not_compressed(gateway):
    seen = _spy_gateway(gateway)
    _chat(gateway, "Remember Acme's roadmap is confidential.", tenant="tenant_acme", user="u_acme")
    seen.clear()
    _chat(gateway, "What is the roadmap?", tenant="tenant_demo", user="u_demo")
    assert all("acme" not in s.lower() for s in seen)


def test_temporary_chat_has_no_memory_compression(gateway):
    seen = _spy_gateway(gateway)
    resp = _chat(gateway, "Remember that I prefer dark mode.", temporary_chat=True)
    assert resp.compression is None
    assert seen == []


def test_policy_still_blocks_secret_with_compression_enabled(gateway):
    # Compression enabled must not stop the policy broker from seeing raw content.
    _spy_gateway(gateway)
    resp = _chat(gateway, "Remember that my API key is sk-test-123456789abcdefghij.")
    assert any(c.decision == Decision.BLOCK for c in resp.candidate_memories)
