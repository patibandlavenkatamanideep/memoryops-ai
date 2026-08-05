"""The data boundary under the governance/evidence reads, checked before enforcement.

Authorization decides *whether* a caller may ask. This file is about what the query
itself is allowed to reach — which has to hold first, because a permission check in
front of an unscoped query only decides who gets the leak.

Two properties:

  1. every identifier-based governance read puts the tenant **in the query**, so an
     identifier belonging to another tenant returns nothing rather than someone
     else's evidence;
  2. the static loop definitions really are static product documentation, which is
     what justifies serving them to any authenticated caller.
"""

from __future__ import annotations

import json

import pytest

from app.db.entities import StoredMemory
from app.loops.registry import list_loop_definitions
from app.schemas.memory import ChatRequest, MemoryType, Sensitivity, Source, Status


def _seed(repo, tenant: str, user: str, content: str) -> StoredMemory:
    return repo.create_memory(
        StoredMemory(
            tenant_id=tenant,
            user_id=user,
            memory_type=MemoryType.preference,
            content=content,
            importance=5,
            confidence=0.8,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="chat", excerpt=content),
        )
    )


# ── loop evidence is tenant-scoped, and fails closed without a tenant ────────
def test_listing_loop_evidence_without_a_tenant_is_refused(gateway, repo):
    """`if tenant_id:` treated an empty string as "no filter requested".

    `tenant_id` is a plain `str` query parameter, so `?tenant_id=` arrived here as
    `""` and returned **every tenant's** loop runs — who did what, across the whole
    store. Postgres already refused this; the in-memory backend did not, so the two
    backends disagreed about invariant #1.
    """
    gateway.handle_chat(
        ChatRequest(tenant_id="acme", user_id="alice", message="Remember I like tea."),
        trace_id="t-acme",
    )
    gateway.handle_chat(
        ChatRequest(tenant_id="evilcorp", user_id="mallory", message="Remember I like ale."),
        trace_id="t-evil",
    )

    for bad_tenant in ("", None):
        with pytest.raises(ValueError, match="tenant_id is required"):
            repo.list_loop_runs(tenant_id=bad_tenant)
        with pytest.raises(ValueError, match="tenant_id is required"):
            repo.list_loop_events(tenant_id=bad_tenant)

    # Scoped reads still work and see only their own tenant.
    acme = repo.list_loop_runs(tenant_id="acme")
    assert acme, "the scoped read must still return this tenant's evidence"
    assert {r.tenant_id for r in acme} == {"acme"}


def test_a_loop_run_id_from_another_tenant_yields_nothing(gateway, repo):
    """An opaque id is not an authorization token.

    Loop events can be fetched by `loop_run_id`, which is unguessable — but
    unguessable is not the same as scoped, and the tenant stays a predicate so a
    leaked or brute-forced id still returns nothing.
    """
    gateway.handle_chat(
        ChatRequest(tenant_id="acme", user_id="alice", message="Remember I like tea."),
        trace_id="t-acme",
    )
    acme_run = repo.list_loop_runs(tenant_id="acme")[0]

    assert repo.list_loop_events(loop_run_id=acme_run.id, tenant_id="acme")
    assert repo.list_loop_events(loop_run_id=acme_run.id, tenant_id="evilcorp") == []
    assert repo.list_loop_runs(trace_id="t-acme", tenant_id="evilcorp") == []


def test_audit_evidence_is_tenant_scoped(gateway, repo):
    gateway.handle_chat(
        ChatRequest(tenant_id="acme", user_id="alice", message="Remember I like tea."),
        trace_id="t-acme",
    )
    assert repo.list_audit("acme", "alice")
    assert repo.list_audit("evilcorp", "mallory") == []


# ── evidence + retention reports ─────────────────────────────────────────────
def test_evidence_reports_cannot_reach_another_tenants_memory(api_client):
    """The reports take `memory_id` from the path, so the lookup behind them is the
    thing that matters — `repo.get_memory(tenant, user, id)`, never a global load."""
    client, repo = api_client
    theirs = _seed(repo, "other_tenant", "someone", "their private note")

    for path in (
        f"/api/evidence/deletion/{theirs.id}",
        f"/api/evidence/lifecycle/{theirs.id}",
    ):
        r = client.get(f"{path}?tenant_id=t1&user_id=u1")
        assert r.status_code == 200
        # Answered, but with no knowledge of the record — see the note below.
        assert r.json()["found"] is False
        assert "their private note" not in r.text

    r = client.get(f"/api/retention/memory/{theirs.id}?tenant_id=t1&user_id=u1")
    assert r.status_code == 404
    assert "their private note" not in r.text


def test_a_deletion_proof_answers_for_an_unknown_memory_on_purpose(api_client):
    """Why these reports return 200 + `found: false` rather than 404.

    A deletion proof must be answerable for a memory that no longer exists — that is
    the case it is *for*. If the endpoint 404'd whenever the record was absent, it
    would fail on exactly the memories that were most thoroughly forgotten, and
    "prove this is gone" would be unanswerable. `found: false` is the proof.

    It leaks nothing: the lookup is tenant-scoped, so "absent" covers never-existed,
    hard-purged, and belongs-to-another-tenant without distinguishing them.
    """
    client, _repo = api_client
    r = client.get("/api/evidence/deletion/never-existed?tenant_id=t1&user_id=u1")
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert "no such memory in scope" in body["detail"]


def test_an_evidence_bundle_for_another_tenants_trace_is_empty(api_client):
    client, _repo = api_client
    client.post("/api/chat", json={"tenant_id": "t1", "user_id": "u1", "message": "hello"})
    r = client.get("/api/evidence/response/some-other-tenants-trace?tenant_id=t1&user_id=u1")
    assert r.status_code == 200
    assert r.json()["event_count"] == 0
    assert r.json()["events"] == []


# ── the static loop definitions ──────────────────────────────────────────────
def test_loop_definitions_carry_nothing_that_needs_a_permission():
    """What justifies serving these to any authenticated caller.

    They are classified `authenticated` rather than behind a permission, which is
    only defensible while they stay static product documentation. If a prompt,
    provider name, environment value, or deployment detail is ever added, this fails
    and the route has to be reclassified before it ships.
    """
    blob = json.dumps([d.model_dump() for d in list_loop_definitions()]).lower()

    forbidden = {
        "prompt text": ("you are ", "system prompt", "assistant:", "instruction:"),
        "environment": ("memoryops_", "database_url", "postgres://", "redis://", "api_key"),
        "provider": ("openai", "anthropic", "gemini", "qdrant", "lancedb", "weaviate", "pgvector"),
        "deployment": ("railway", "docker", "localhost", "127.0.0.1", "http://", "https://"),
        "tenant data": ("tenant_id=", "user_id=", "@"),
    }
    for label, needles in forbidden.items():
        hits = [n for n in needles if n in blob]
        assert not hits, f"loop definitions now contain {label}: {hits} — reclassify the route"

    # Descriptive prose about secret *scanning* is expected; a secret-shaped value is not.
    assert "pii/secret scan" in blob, "sanity: the descriptive text is still there"
    assert not [w for w in blob.split() if len(w) > 40], "no opaque blobs"


def test_loop_definitions_are_identical_for_every_caller():
    """No tenant, user, or request state reaches them — so there is nothing for a
    permission to protect and nothing that could differ between callers."""
    first = [d.model_dump() for d in list_loop_definitions()]
    second = [d.model_dump() for d in list_loop_definitions()]
    assert first == second
    assert {d["id"] for d in first} == {
        "memory.write",
        "memory.read",
        "memory.governance",
        "memory.evaluation",
        "release.gate",
        "learning.continuous",
    }
