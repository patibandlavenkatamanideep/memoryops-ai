"""Content edits must go through governance (invariant #5).

`PATCH /api/memories/{id}` assigned edited content straight onto the stored row::

    m.content = patch.content
    m.normalized_content = " ".join(patch.content.lower().split())

Nothing else ran — no policy broker, no secret scan, no sensitivity
reclassification, no legal-hold check, and the embedding was never touched, so the
row kept the vector of its *previous* content.

The two headline regressions are:

  * a safe memory edited into a credential must be **blocked**, leaving the
    original memory unchanged;
  * a safe memory edited at all must **not** keep the old embedding active for the
    new content.
"""

from __future__ import annotations

from app.db.entities import StoredMemory
from app.embeddings import embed
from app.schemas.memory import MemoryType, Sensitivity, Source, Status

from ._secret_fixtures import FAKE_INJECTION, FAKE_PROVIDER_KEY, FAKE_SECRET_ASSIGNMENT

_Q = "?tenant_id=t1&user_id=u1"


def _seed(
    repo,
    *,
    content: str = "prefers dark mode dashboards",
    status: Status = Status.active,
    sensitivity: Sensitivity = Sensitivity.low,
) -> StoredMemory:
    return repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content=content,
            normalized_content=" ".join(content.lower().split()),
            embedding=embed(content),
            importance=7,
            confidence=0.9,
            sensitivity=sensitivity,
            status=status,
            source=Source(kind="chat", excerpt=content),
        )
    )


def _patch(client, memory_id: str, **fields):
    return client.patch(
        f"/api/memories/{memory_id}",
        json={"tenant_id": "t1", "user_id": "u1", **fields},
    )


# ── critical regression 1: edit to a credential is blocked ───────────────────
def test_editing_safe_content_into_an_api_key_is_blocked(api_client):
    client, repo = api_client
    m = _seed(repo, content="prefers dark mode dashboards")
    original_content = m.content
    original_embedding = list(m.embedding)
    original_revision = m.revision

    r = _patch(client, m.id, content=FAKE_PROVIDER_KEY)
    assert r.status_code == 422, (
        "an edit that introduces a credential must be refused; creation BLOCKs the "
        "same content, and the edit path bypassed the broker entirely"
    )

    after = repo.get_memory("t1", "u1", m.id)
    assert after.content == original_content, "the original memory must be untouched"
    assert after.embedding == original_embedding
    assert after.revision == original_revision
    assert after.status is Status.active


def test_editing_into_a_generic_secret_phrase_is_blocked(api_client):
    client, repo = api_client
    m = _seed(repo)
    r = _patch(client, m.id, content=FAKE_SECRET_ASSIGNMENT)
    assert r.status_code == 422
    assert repo.get_memory("t1", "u1", m.id).content == m.content


def test_editing_in_a_prompt_injection_payload_is_blocked(api_client):
    client, repo = api_client
    m = _seed(repo)
    r = _patch(client, m.id, content=FAKE_INJECTION)
    assert r.status_code == 422
    assert repo.get_memory("t1", "u1", m.id).content == m.content


# ── critical regression 2: the old embedding cannot survive the edit ─────────
def test_edited_content_never_keeps_the_previous_embedding(api_client):
    client, repo = api_client
    m = _seed(repo, content="prefers dark mode dashboards")
    old_embedding = list(m.embedding)
    assert old_embedding, "fixture must start with a real vector"

    r = _patch(client, m.id, content="prefers light mode dashboards with large fonts")
    assert r.status_code == 200

    after = repo.get_memory("t1", "u1", m.id)
    assert after.content == "prefers light mode dashboards with large fonts"
    assert after.embedding != old_embedding, (
        "the row kept the vector of its previous content — dense retrieval would "
        "match the old text and return the new text"
    )
    # And it is the vector of the *new* content, not merely different.
    assert after.embedding == embed(after.content)


def test_normalized_content_follows_the_edit(api_client):
    client, repo = api_client
    m = _seed(repo, content="prefers dark mode")
    _patch(client, m.id, content="Prefers   LIGHT   Mode")
    after = repo.get_memory("t1", "u1", m.id)
    assert after.normalized_content == "prefers light mode"


def test_a_failed_embedding_leaves_no_vector_rather_than_a_stale_one(api_client, monkeypatch):
    """Consistent with the embedding-integrity rule: absent beats confidently wrong."""
    from app.services import update_service

    client, repo = api_client
    m = _seed(repo, content="prefers dark mode dashboards")
    assert m.embedding

    def _boom(_text):
        raise RuntimeError("embedding provider unreachable")

    monkeypatch.setattr(update_service, "embed", _boom)
    r = _patch(client, m.id, content="prefers light mode dashboards")
    assert r.status_code == 200

    after = repo.get_memory("t1", "u1", m.id)
    assert after.content == "prefers light mode dashboards"
    assert after.embedding == [], "a stale vector must never survive a content change"


# ── sensitivity is recomputed, not inherited ─────────────────────────────────
def test_editing_low_sensitivity_content_into_pii_re_gates_the_memory(api_client):
    client, repo = api_client
    m = _seed(repo, content="prefers dark mode", sensitivity=Sensitivity.low)

    r = _patch(client, m.id, content="my social security number is 555-01-9999")
    assert r.status_code == 200

    after = repo.get_memory("t1", "u1", m.id)
    assert after.sensitivity is not Sensitivity.low, (
        "sensitivity was inherited from the stored row, so an edit into PII kept a "
        "low label and every sensitivity-keyed control stopped applying"
    )
    assert after.status is Status.pending, "sensitive edits return to the approval queue"


def test_a_benign_edit_stays_active_and_low(api_client):
    client, repo = api_client
    m = _seed(repo)
    r = _patch(client, m.id, content="prefers light mode dashboards")
    assert r.status_code == 200
    after = repo.get_memory("t1", "u1", m.id)
    assert after.status is Status.active
    assert after.sensitivity is Sensitivity.low


# ── legal hold preserves content ─────────────────────────────────────────────
def test_content_cannot_be_edited_under_legal_hold(api_client):
    """A hold preserves content; editing destroys it as surely as deleting."""
    client, repo = api_client
    m = _seed(repo, content="the held statement")

    hold = client.post(
        "/api/retention/legal-hold",
        json={
            "tenant_id": "t1",
            "user_id": "u1",
            "memory_id": m.id,
            "on": True,
            "reason": "litigation",
        },
    )
    assert hold.status_code == 200

    r = _patch(client, m.id, content="a different statement")
    assert r.status_code == 409
    assert repo.get_memory("t1", "u1", m.id).content == "the held statement"


def test_governance_transitions_still_work_under_legal_hold(api_client):
    """The hold protects *content*, not the approval workflow."""
    client, repo = api_client
    m = _seed(repo, status=Status.pending)
    client.post(
        "/api/retention/legal-hold",
        json={
            "tenant_id": "t1",
            "user_id": "u1",
            "memory_id": m.id,
            "on": True,
            "reason": "litigation",
        },
    )
    assert _patch(client, m.id, status="active").status_code == 200


# ── deleted memories ─────────────────────────────────────────────────────────
def test_deleted_memory_cannot_be_edited(api_client):
    client, repo = api_client
    m = _seed(repo, status=Status.deleted)
    assert _patch(client, m.id, content="resurrected text").status_code == 404


# ── optimistic concurrency ───────────────────────────────────────────────────
def test_revision_increments_on_each_governed_edit(api_client):
    client, repo = api_client
    m = _seed(repo)
    assert m.revision == 1

    assert _patch(client, m.id, content="first edit").json()["revision"] == 2
    assert _patch(client, m.id, content="second edit").json()["revision"] == 3


def test_a_stale_expected_revision_is_rejected(api_client):
    client, repo = api_client
    m = _seed(repo)

    # Two callers both read revision 1; the first edit wins.
    assert _patch(client, m.id, content="winner", expected_revision=1).status_code == 200
    loser = _patch(client, m.id, content="loser", expected_revision=1)
    assert loser.status_code == 409, "a lost update must be refused, not silently applied"
    assert repo.get_memory("t1", "u1", m.id).content == "winner"


def test_a_matching_expected_revision_succeeds(api_client):
    client, repo = api_client
    m = _seed(repo)
    current = _patch(client, m.id, content="first").json()["revision"]
    assert _patch(client, m.id, content="second", expected_revision=current).status_code == 200


def test_omitting_expected_revision_keeps_last_write_wins(api_client):
    """Additive: existing clients that never send it are unaffected."""
    client, repo = api_client
    m = _seed(repo)
    assert _patch(client, m.id, content="a").status_code == 200
    assert _patch(client, m.id, content="b").status_code == 200
    assert repo.get_memory("t1", "u1", m.id).content == "b"


# ── audit evidence ───────────────────────────────────────────────────────────
def test_audit_records_before_and_after_hashes_without_the_content(api_client):
    from app.services.update_service import content_hash

    client, repo = api_client
    m = _seed(repo, content="prefers dark mode")
    before = content_hash("prefers dark mode")

    assert _patch(client, m.id, content="prefers light mode").status_code == 200

    events = client.get(f"/api/memories/{m.id}/audit{_Q}").json()
    edit = next(e for e in events if e["action"] == "memory_content_updated")
    meta = edit["metadata"]
    assert meta["previous_content_hash"] == before
    assert meta["new_content_hash"] == content_hash("prefers light mode")
    assert meta["policy_version"]
    assert meta["revision"] == 2
    # Hashes, never the text — the trail is read by operators who may not be
    # cleared for the memory itself.
    blob = str(meta)
    assert "prefers dark mode" not in blob
    assert "prefers light mode" not in blob


def test_a_sensitive_edit_is_audited_distinctly(api_client):
    client, repo = api_client
    m = _seed(repo)
    _patch(client, m.id, content="my social security number is 555-01-9999")
    actions = {e["action"] for e in client.get(f"/api/memories/{m.id}/audit{_Q}").json()}
    assert "memory_content_update_pending_approval" in actions
    assert "memory_updated" not in actions, "the generic action no longer stands in for an edit"


# ── the update path is not the creation path ─────────────────────────────────
def test_editing_does_not_dedup_against_itself(api_client):
    """Creation's `UPDATE_EXISTING` would match the memory being edited.

    Reusing `evaluate()` would turn an edit into a reinforcement of itself and
    silently keep the old content.
    """
    client, repo = api_client
    m = _seed(repo, content="prefers dark mode dashboards")
    before = m.reinforcement_count

    r = _patch(client, m.id, content="prefers dark mode dashboards and large fonts")
    assert r.status_code == 200
    after = repo.get_memory("t1", "u1", m.id)
    assert after.content == "prefers dark mode dashboards and large fonts"
    assert after.reinforcement_count == before, "an edit is not a reinforcement"


def test_a_low_importance_edit_is_not_silently_dropped(api_client):
    """Creation's low-utility drop would discard the edit and keep the old content."""
    client, repo = api_client
    m = repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content="prefers dark mode",
            importance=1,  # below the creation floor
            confidence=0.5,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="chat", excerpt="prefers dark mode"),
        )
    )
    r = _patch(client, m.id, content="prefers light mode")
    assert r.status_code == 200
    assert repo.get_memory("t1", "u1", m.id).content == "prefers light mode"


# ── concurrency: the guard must be in the write, not a pre-check ─────────────
def test_two_concurrent_edits_with_the_same_expected_revision_yield_one_winner(api_client):
    """The race a Python-side check cannot close.

    Both requests read revision N and both pass any caller-side comparison; the
    embedding call then sits between the read and the write, widening the window.
    Only a compare-and-swap at the database (`WHERE revision = :expected`) makes
    exactly one of them win.

    Threaded because sync FastAPI routes run in a thread pool, so this is the real
    interleaving, not a simulation.
    """
    import threading

    client, repo = api_client
    m = _seed(repo, content="prefers dark mode")
    assert m.revision == 1

    results: list[int] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def _edit(text: str) -> None:
        barrier.wait(timeout=5)  # maximise overlap
        r = client.patch(
            f"/api/memories/{m.id}",
            json={
                "tenant_id": "t1",
                "user_id": "u1",
                "content": text,
                "expected_revision": 1,
            },
        )
        with lock:
            results.append(r.status_code)

    threads = [
        threading.Thread(target=_edit, args=("winner takes the slot",)),
        threading.Thread(target=_edit, args=("loser must be refused",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert sorted(results) == [200, 409], (
        f"exactly one writer must win; got {results}. Both succeeding means the "
        "revision check is a pre-check rather than a compare-and-swap."
    )
    # The surviving row is one of the two edits, at revision 2 — never a blend.
    after = repo.get_memory("t1", "u1", m.id)
    assert after.content in ("winner takes the slot", "loser must be refused")
    assert after.revision == 2


def test_a_worker_style_mutation_invalidates_a_held_revision(api_client):
    """`revision` is a row revision, so any mutation — not just a content edit —
    causes a stale content edit to be refused. That is what makes it one shared
    concurrency contract between the control plane and the lifecycle workers."""
    client, repo = api_client
    m = _seed(repo, content="prefers dark mode")

    # A non-content mutation, as a worker (decay/archive) would perform.
    m.weight = 0.5
    repo.update_memory(m)

    stale = _patch(client, m.id, content="edited from a stale read", expected_revision=1)
    assert stale.status_code == 409
