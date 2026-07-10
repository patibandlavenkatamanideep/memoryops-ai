"""Enterprise Evidence Layer (v2.0, ADR-024).

Proves the audit trail is tamper-evident (hash chain), that tampering is detected,
and that the evidence reports (bundle / deletion proof / policy / lifecycle) are
tenant-scoped and verifiable.
"""

from __future__ import annotations

from app.evidence import GENESIS, compute_entry_hash, verify_chain
from app.evidence.reports import (
    deletion_proof,
    evidence_bundle,
    lifecycle_export,
    policy_report,
    verify_audit,
)
from app.schemas.memory import ChatRequest


def _chat(gateway, message, *, tenant="t1", user="u1", trace_id="tr"):
    return gateway.handle_chat(
        ChatRequest(tenant_id=tenant, user_id=user, message=message), trace_id=trace_id
    )


# ── hash chain ───────────────────────────────────────────────────────────────────
def test_audit_events_are_hash_chained(gateway, repo):
    _chat(gateway, "Remember that I prefer dark mode.")
    events = list(reversed(repo.list_audit("t1", "u1", limit=1000)))
    assert events
    assert all(e.entry_hash for e in events)
    # Each event's hash recomputes from its content + prev link.
    for e in events:
        assert e.entry_hash == compute_entry_hash(e, e.prev_hash)
    assert verify_audit(repo, "t1")["ok"]


def test_tampering_breaks_the_chain(gateway, repo):
    _chat(gateway, "Remember that I prefer dark mode.")
    _chat(gateway, "Remember that I use Postgres.")
    events = list(reversed(repo.list_audit("t1", limit=1000)))
    assert verify_chain(events)["ok"]

    # Tamper with a persisted event's content — hash no longer matches.
    events_middle = events[len(events) // 2]
    events_middle.reason = "TAMPERED"
    result = verify_chain(events)
    assert result["ok"] is False and result["broken_at"] == events_middle.id


def test_deleting_an_event_breaks_the_chain(gateway, repo):
    _chat(gateway, "Remember that I prefer dark mode.")
    _chat(gateway, "Remember that I use Postgres.")
    events = list(reversed(repo.list_audit("t1", limit=1000)))
    assert len(events) >= 2 and verify_chain(events)["ok"]
    # Drop the genesis event → nothing links to GENESIS → the chain can't start.
    genesis_event = next(e for e in events if e.prev_hash == GENESIS)
    truncated = [e for e in events if e.id != genesis_event.id]
    assert verify_chain(truncated)["ok"] is False


def test_chain_is_per_tenant_isolated(gateway, repo):
    _chat(gateway, "Remember I prefer dark mode.", tenant="acme", user="u1", trace_id="a")
    _chat(gateway, "Remember I prefer light mode.", tenant="globex", user="u1", trace_id="b")
    acme, globex = verify_audit(repo, "acme"), verify_audit(repo, "globex")
    assert acme["ok"] and globex["ok"]
    # Each tenant's chain verifies independently and has its own events.
    assert acme["length"] >= 1 and globex["length"] >= 1


# ── evidence reports ─────────────────────────────────────────────────────────────
def test_evidence_bundle_collects_response_events(gateway, repo):
    _chat(gateway, "Remember I prefer dark mode.", trace_id="resp-1")
    bundle = evidence_bundle(repo, "t1", "u1", "resp-1")
    assert bundle["trace_id"] == "resp-1"
    assert bundle["event_count"] >= 1
    assert all(e["trace_id"] == "resp-1" for e in bundle["events"])
    assert bundle["bundle_hash"] and bundle["chain_intact"] is True


def test_deletion_proof_reports_forgotten_memory(gateway, repo):
    _chat(gateway, "Remember that I prefer Vendor X.")
    mem = repo.list_memories("t1", "u1")[0]
    repo.soft_delete("t1", "u1", mem.id)
    proof = deletion_proof(repo, "t1", "u1", mem.id)
    assert proof["found"] and proof["checks"]["status_is_deleted"]
    assert proof["checks"]["excluded_from_active_retrieval"]
    assert proof["chain_intact"] is True


def test_policy_and_lifecycle_reports_are_scoped(gateway, repo):
    _chat(gateway, "Remember that I prefer Vendor X.")
    mem = repo.list_memories("t1", "u1")[0]

    report = policy_report(repo, "t1", "u1")
    assert report["total_events"] >= 1 and report["chain_intact"]
    # Cross-tenant scope sees nothing.
    assert policy_report(repo, "other", "u1")["total_events"] == 0

    export = lifecycle_export(repo, "t1", "u1", mem.id)
    assert export["found"] and export["status"] == "active"
    assert "governance" in export and "lineage" in export
    assert export["audit_timeline"]


# ── endpoint ─────────────────────────────────────────────────────────────────────
def test_evidence_endpoints(api_client):
    client, _ = api_client
    client.post("/api/chat", json={"tenant_id": "t1", "user_id": "u1", "message": "hi"},
                headers={"x-trace-id": "e2e-1"})
    r = client.get("/api/evidence/audit/verify?tenant_id=t1&user_id=u1")
    assert r.status_code == 200 and r.json()["ok"] is True
    b = client.get("/api/evidence/response/e2e-1?tenant_id=t1&user_id=u1")
    assert b.status_code == 200 and b.json()["trace_id"] == "e2e-1"
