"""Semantic sensitivity classification, proven on both write paths.

Classification previously matched only *structural* patterns — SSN and card digit
shapes, API-key formats. Semantic disclosures scored `low` and were stored `active`:

    "my password is hunter2"            -> low / active
    "my HIV status is positive"         -> low / active
    "I take sertraline for depression"  -> low / active
    "my salary is $250,000"             -> low / active

Every downstream control keys off sensitivity — approval gating, the recall gate's
audience clearance, the admission gate — so for exactly the categories those controls
exist to protect, they were inert. A plaintext password was retrievable into a
`public`-audience response.

The parametrised matrix runs each case through **creation** and through an
**existing-memory content edit**, because the same content must reach the same
outcome regardless of how it enters the system — that equivalence is precisely what
the edit path used to break.
"""

from __future__ import annotations

import pytest

from app.core.sensitivity import (
    BLOCK,
    PENDING_APPROVAL,
    SAVE,
    classify,
    is_memory_control_instruction,
)
from app.db.entities import StoredMemory
from app.schemas.memory import MemoryType, Sensitivity, Source, Status

_Q = "?tenant_id=t1&user_id=u1"

# (text, category, recommended disposition)
POSITIVE_CASES = [
    ("my password is hunter2", "credential", BLOCK),
    ("my PIN is 4281", "credential", BLOCK),
    ("my recovery code is 782144", "recovery_secret", BLOCK),
    ("my security answer is bluebird", "credential", BLOCK),
    ("my HIV status is positive", "medical", PENDING_APPROVAL),
    ("I was diagnosed with diabetes", "medical", PENDING_APPROVAL),
    ("I take sertraline for depression", "mental_health", PENDING_APPROVAL),
    ("my salary is $250,000", "financial", PENDING_APPROVAL),
    ("I owe $18,000 in credit-card debt", "financial", PENDING_APPROVAL),
    ("my bank balance is $18,400", "financial", PENDING_APPROVAL),
    ("my home address is 123 Main Street", "location", PENDING_APPROVAL),
]

# A sensitive keyword is not a disclosure. These discuss a topic rather than reveal
# a fact about the speaker, and must not classify as sensitive.
NEGATIVE_CASES = [
    "I forgot my password",
    "I use a password manager",
    "How should password hashing work?",
    "Sertraline is a commonly prescribed medication",
    "I am reading research about HIV",
    "What is the average software engineer salary?",
    "This document explains bank routing numbers",
    "I prefer dark mode dashboards",
    "my favourite food is ramen",
]

# Instructions *about* memory, not facts to store.
MEMORY_CONTROL_CASES = [
    "do not remember my password",
    "never save my password",
    "forget my salary",
    "do not store my medical information",
    "I don't want you to remember my address",
]


def _seed(repo, content: str = "prefers dark mode dashboards") -> StoredMemory:
    return repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content=content,
            normalized_content=content.lower(),
            importance=7,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="chat", excerpt=content),
        )
    )


# ── layer 1: detection ───────────────────────────────────────────────────────
@pytest.mark.parametrize(("text", "category", "disposition"), POSITIVE_CASES)
def test_positive_cases_are_classified(text, category, disposition):
    a = classify(text)
    assert a.findings, f"no rule fired for: {text}"
    assert category in a.categories
    assert a.recommended_disposition == disposition
    assert a.sensitivity is Sensitivity.high


@pytest.mark.parametrize("text", NEGATIVE_CASES)
def test_negative_cases_do_not_trigger_on_a_keyword_alone(text):
    a = classify(text)
    assert not a.findings, f"false positive on: {text} ({list(a.rule_ids)})"
    assert a.recommended_disposition == SAVE
    assert a.sensitivity is Sensitivity.low


def test_findings_carry_a_rule_id_and_category_not_the_matched_value():
    a = classify("my password is hunter2")
    finding = a.findings[0]
    assert finding.rule_id == "credential.password_first_person"
    assert finding.category == "credential"
    # The value must never appear anywhere in the structured result.
    assert "hunter2" not in repr(a)


def test_precedence_is_deterministic():
    """BLOCK outranks PENDING_APPROVAL; high outranks medium."""
    a = classify("my password is hunter2 and I was diagnosed with diabetes")
    assert a.recommended_disposition == BLOCK
    assert a.sensitivity is Sensitivity.high
    assert {"credential", "medical"} <= set(a.categories)


def test_classification_is_a_recommendation_not_a_decision():
    """The assessment names a disposition; only the broker acts on it."""
    a = classify("my password is hunter2")
    assert a.recommended_disposition == BLOCK
    assert not hasattr(a, "decision")


# ── layer 3: both write paths agree ──────────────────────────────────────────
@pytest.mark.parametrize(("text", "category", "disposition"), POSITIVE_CASES)
def test_creation_path_applies_the_recommendation(api_client, text, category, disposition):
    client, repo = api_client
    r = client.post(
        "/api/chat", json={"tenant_id": "t1", "user_id": "u1", "message": f"Remember: {text}"}
    )
    assert r.status_code == 200

    stored = [m for m in repo.list_memories("t1", "u1") if m.status is not Status.deleted]
    if disposition == BLOCK:
        assert not any(
            m.status is Status.active for m in stored
        ), f"blocked content was stored active: {text}"
    else:
        assert stored, f"nothing stored for: {text}"
        assert all(m.sensitivity is Sensitivity.high for m in stored)
        assert all(m.status is Status.pending for m in stored)


@pytest.mark.parametrize(("text", "category", "disposition"), POSITIVE_CASES)
def test_edit_path_reaches_the_same_outcome_as_creation(api_client, text, category, disposition):
    """The equivalence the edit path used to break."""
    client, repo = api_client
    m = _seed(repo)

    r = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": text},
    )
    after = repo.get_memory("t1", "u1", m.id)

    if disposition == BLOCK:
        assert r.status_code == 422, f"edit into {category} must be refused: {text}"
        assert after.content == "prefers dark mode dashboards"
        assert after.sensitivity is Sensitivity.low
        assert after.status is Status.active
    else:
        assert r.status_code == 200, r.text
        assert after.content == text
        assert after.sensitivity is Sensitivity.high
        assert after.status is Status.pending


@pytest.mark.parametrize("text", NEGATIVE_CASES)
def test_negative_cases_are_editable_without_re_gating(api_client, text):
    client, repo = api_client
    m = _seed(repo)
    r = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": text},
    )
    assert r.status_code == 200, f"benign content was gated: {text}"
    after = repo.get_memory("t1", "u1", m.id)
    assert after.status is Status.active
    assert after.sensitivity is Sensitivity.low


# ── memory-control instructions store nothing ────────────────────────────────
@pytest.mark.parametrize("text", MEMORY_CONTROL_CASES)
def test_memory_control_instructions_are_recognised(text):
    assert is_memory_control_instruction(text), f"not recognised: {text}"


@pytest.mark.parametrize("text", MEMORY_CONTROL_CASES)
def test_memory_control_instructions_create_no_memory(api_client, text):
    """The expected result is *no persistent memory*, not a stored high-sensitivity
    record and not merely a BLOCK verdict — storing the sentence would be the same
    disclosure by another route."""
    client, repo = api_client
    r = client.post("/api/chat", json={"tenant_id": "t1", "user_id": "u1", "message": text})
    assert r.status_code == 200
    assert repo.list_memories("t1", "u1") == [], f"a memory was created for: {text}"


@pytest.mark.parametrize("text", MEMORY_CONTROL_CASES)
def test_policy_refuses_a_memory_control_candidate_independently(repo, text):
    """Second, independent guard: even if a malformed extractor emits a candidate,
    policy must not store it."""
    from app.db.entities import StoredSettings
    from app.schemas.memory import CandidateMemory, Decision
    from app.services.policy_broker import PolicyBroker

    candidate = CandidateMemory(
        content=text,
        type=MemoryType.preference,
        sensitivity=Sensitivity.low,
        importance=9,  # high enough that the utility floor cannot be the reason
        confidence=0.95,
        reason="malformed extractor output",
    )
    outcome = PolicyBroker(repo).evaluate(
        candidate,
        tenant_id="t1",
        user_id="u1",
        settings=StoredSettings(tenant_id="t1", user_id="u1"),
    )
    assert outcome.decision is not Decision.SAVE
    assert outcome.decision is not Decision.PENDING_APPROVAL


# ── audit evidence stays content-free ────────────────────────────────────────
def test_audit_records_categories_and_rule_ids_but_never_the_value(api_client):
    client, repo = api_client
    m = _seed(repo)

    assert (
        client.patch(
            f"/api/memories/{m.id}",
            json={"tenant_id": "t1", "user_id": "u1", "content": "my salary is $250,000"},
        ).status_code
        == 200
    )

    events = client.get(f"/api/memories/{m.id}/audit{_Q}").json()
    edit = next(e for e in events if e["action"].startswith("memory_content_update"))
    meta = edit["metadata"]
    assert "financial" in meta["sensitivity_categories"]
    assert "financial.amount_first_person" in meta["sensitivity_rule_ids"]
    assert meta["sensitivity_finding_count"] == 1
    assert meta["new_sensitivity"] == "high"

    blob = str(meta)
    for secret in ("250,000", "$250", "salary is"):
        assert secret not in blob, f"audit metadata leaked the matched value: {secret}"


# ── mutation guarantees ──────────────────────────────────────────────────────
def test_edit_to_a_credential_leaves_every_field_unchanged(api_client):
    from app.embeddings import embed

    client, repo = api_client
    m = _seed(repo)
    m.embedding = embed(m.content)
    repo.update_memory(m)
    before = repo.get_memory("t1", "u1", m.id)
    snapshot = (
        before.content,
        list(before.embedding),
        before.sensitivity,
        before.status,
        before.revision,
    )

    r = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": "my password is hunter2"},
    )
    assert r.status_code == 422

    after = repo.get_memory("t1", "u1", m.id)
    assert (
        after.content,
        list(after.embedding),
        after.sensitivity,
        after.status,
        after.revision,
    ) == snapshot


def test_edit_to_a_medical_disclosure_regates_and_re_embeds(api_client):
    from app.embeddings import embed

    client, repo = api_client
    m = _seed(repo)
    m.embedding = embed(m.content)
    repo.update_memory(m)
    revision_before = repo.get_memory("t1", "u1", m.id).revision
    old_embedding = list(repo.get_memory("t1", "u1", m.id).embedding)

    r = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": "I was diagnosed with diabetes"},
    )
    assert r.status_code == 200

    after = repo.get_memory("t1", "u1", m.id)
    assert after.sensitivity is Sensitivity.high
    assert after.status is Status.pending
    assert after.embedding != old_embedding
    assert after.embedding == embed("I was diagnosed with diabetes")
    assert after.revision == revision_before + 1


def test_two_concurrent_sensitive_edits_yield_one_winner(api_client):
    import threading

    client, repo = api_client
    m = _seed(repo)
    start = repo.get_memory("t1", "u1", m.id).revision

    results: list[int] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def _edit(text: str) -> None:
        barrier.wait(timeout=5)
        r = client.patch(
            f"/api/memories/{m.id}",
            json={
                "tenant_id": "t1",
                "user_id": "u1",
                "content": text,
                "expected_revision": start,
            },
        )
        with lock:
            results.append(r.status_code)

    threads = [
        threading.Thread(target=_edit, args=("I was diagnosed with diabetes",)),
        threading.Thread(target=_edit, args=("my salary is $250,000",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert sorted(results) == [200, 409], f"expected one winner, got {results}"
    after = repo.get_memory("t1", "u1", m.id)
    assert after.status is Status.pending
    assert after.revision == start + 1


# ── review edge cases ────────────────────────────────────────────────────────
# The 73 cases above classify whole, single-clause messages. These cover the four
# gaps found in review: mixed clauses, mixed instructions, pre-existing rows, and
# evidence parity between the two write paths.


# 1. An educational clause must not exempt a separate disclosure clause.
@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("I am reading research about HIV. My HIV status is positive.", "medical"),
        ("What is the average software engineer salary? My salary is $250,000.", "financial"),
        (
            "Sertraline is a commonly prescribed medication. I take sertraline for depression.",
            "mental_health",
        ),
        ("How should password hashing work? My password is hunter2.", "credential"),
        ("This document explains routing numbers; my bank balance is $18,400.", "financial"),
    ],
)
def test_an_educational_clause_does_not_exempt_a_disclosure_clause(text, category):
    a = classify(text)
    assert a.findings, f"whole-message framing suppressed a real disclosure: {text}"
    assert category in a.categories


def test_a_wholly_educational_message_is_still_clean():
    """The clause fix must not turn the framing guard off."""
    for text in NEGATIVE_CASES:
        assert not classify(text).findings, text


# 2. A memory-control clause must not suppress a legitimate fact beside it.
def test_a_memory_control_clause_does_not_suppress_an_unrelated_fact(api_client):
    client, repo = api_client
    r = client.post(
        "/api/chat",
        json={
            "tenant_id": "t1",
            "user_id": "u1",
            "message": "Do not remember my password, but remember that I prefer dark mode.",
        },
    )
    assert r.status_code == 200

    stored = repo.list_memories("t1", "u1")
    assert stored, "the whole message was discarded, losing a legitimate preference"
    blob = " ".join(m.content.lower() for m in stored)
    assert "dark mode" in blob
    assert "password" not in blob, "the credential clause was stored"


def test_strip_leaves_only_the_non_instruction_clauses():
    from app.core.sensitivity import strip_memory_control_clauses

    remainder = strip_memory_control_clauses(
        "Do not remember my password, but remember that I prefer dark mode."
    )
    assert "dark mode" in remainder
    assert "password" not in remainder


def test_forget_is_distinguished_from_do_not_remember():
    """`forget my salary` asks to remove existing memory; `do not remember my
    salary` only prevents new persistence. Both suppress a new candidate, but the
    distinction has to exist before the forget workflow can use it."""
    from app.core.sensitivity import is_forget_request

    assert is_forget_request("forget my salary")
    assert not is_forget_request("do not remember my salary")
    # Both are still memory-control, so neither creates a memory.
    assert is_memory_control_instruction("forget my salary")
    assert is_memory_control_instruction("do not remember my salary")


def test_forget_does_not_silently_delete_existing_memory(api_client):
    """Deliberate: a chat phrase must not perform a destructive action outside the
    governed deletion workflow (legal hold, deleted_at, tombstone, lineage, audit)."""
    client, repo = api_client
    m = _seed(repo, content="my salary is $250,000")

    client.post(
        "/api/chat",
        json={"tenant_id": "t1", "user_id": "u1", "message": "forget my salary"},
    )

    after = repo.get_memory("t1", "u1", m.id)
    assert after is not None and after.status is not Status.deleted
    assert after.deleted_at is None


# 3. Rows stored before the classifier existed are gated at read time.
def test_a_pre_upgrade_low_active_credential_row_is_withheld(api_client):
    """#103 classifies at write time. A row already stored `low`/`active` keeps its
    label, so without read-time re-classification the headline fix would apply only
    to content entering after deploy."""
    client, repo = api_client
    repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content="my password is hunter2",
            importance=8,
            confidence=0.9,
            sensitivity=Sensitivity.low,  # as stored before the classifier existed
            status=Status.active,
            source=Source(kind="chat", excerpt="my password is hunter2"),
        )
    )

    r = client.post(
        "/api/chat",
        json={
            "tenant_id": "t1",
            "user_id": "u1",
            "message": "what is my password?",
            "audience": "public",
        },
    )
    assert r.status_code == 200
    trace = r.json().get("trace") or {}

    assert trace.get("memories_used") == [], "a pre-upgrade credential row entered context"

    body = r.json()
    assert "hunter2" not in str(body), "the withheld value was returned anyway"
    for entry in trace.get("memories_blocked", []):
        assert entry["content_preview"] == "", "a withheld memory returned a content preview"
        assert entry.get("source") in (None, {}), "a withheld memory returned its source excerpt"


def test_read_time_classification_never_lowers_a_stored_label(api_client):
    """Only ever raises: an operator's `high` is not undone by pattern silence."""
    from app.services.effective_sensitivity import effective_sensitivity

    _client, repo = api_client
    m = repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content="prefers dark mode dashboards",
            importance=7,
            confidence=0.9,
            sensitivity=Sensitivity.high,  # deliberately labelled by an operator
            status=Status.active,
            source=Source(kind="chat", excerpt="prefers dark mode dashboards"),
        )
    )
    assert effective_sensitivity(m) is Sensitivity.high


def test_read_time_classification_does_not_mutate_the_row(api_client):
    """Reads must not write: it would produce audit events with no actor and race
    with concurrent edits. Persisting belongs to a reclassification worker."""
    from app.services.effective_sensitivity import effective_sensitivity

    _client, repo = api_client
    m = repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content="my password is hunter2",
            importance=8,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="chat", excerpt="my password is hunter2"),
        )
    )
    assert effective_sensitivity(m) is Sensitivity.high
    assert repo.get_memory("t1", "u1", m.id).sensitivity is Sensitivity.low
    assert repo.get_memory("t1", "u1", m.id).revision == m.revision


# 4. Creation and edit produce the same evidence vocabulary.
def test_creation_audit_carries_the_same_classification_evidence_as_an_edit(api_client):
    client, repo = api_client
    r = client.post(
        "/api/chat",
        json={
            "tenant_id": "t1",
            "user_id": "u1",
            "message": "Remember: my salary is $250,000.",
        },
    )
    assert r.status_code == 200
    stored = repo.list_memories("t1", "u1")
    assert stored

    events = client.get(f"/api/memories/{stored[0].id}/audit{_Q}").json()
    # A sensitive creation is audited as `memory_pending_approval`, a benign one as
    # `memory_created`; both are creation-path events and must carry the evidence.
    created = next(
        e for e in events if e["action"] in ("memory_created", "memory_pending_approval")
    )
    meta = created["metadata"]
    for key in (
        "sensitivity_categories",
        "sensitivity_rule_ids",
        "sensitivity_finding_count",
    ):
        assert key in meta, f"creation audit is missing {key} (edits record it)"
    assert "financial" in meta["sensitivity_categories"]
    assert "250,000" not in str(meta), "creation audit leaked the matched value"


# 5. Memory-control drops are distinguishable from genuine low-utility drops.
def test_memory_control_drop_carries_a_distinct_reason_code(repo):
    """Reusing DROP_LOW_UTILITY for both would contaminate utility metrics:
    'not a memory' and 'a valid memory of low utility' are different outcomes."""
    from app.db.entities import StoredSettings
    from app.schemas.memory import CandidateMemory
    from app.services.policy_broker import (
        REASON_LOW_UTILITY,
        REASON_MEMORY_CONTROL,
        PolicyBroker,
    )

    settings = StoredSettings(tenant_id="t1", user_id="u1")
    broker = PolicyBroker(repo)

    control = broker.evaluate(
        CandidateMemory(
            content="do not remember my password",
            type=MemoryType.preference,
            sensitivity=Sensitivity.low,
            importance=9,
            confidence=0.95,
            reason="x",
        ),
        tenant_id="t1",
        user_id="u1",
        settings=settings,
    )
    assert control.reason_code == REASON_MEMORY_CONTROL

    trivial = broker.evaluate(
        CandidateMemory(
            content="the sky is sometimes blue",
            type=MemoryType.preference,
            sensitivity=Sensitivity.low,
            importance=1,
            confidence=0.5,
            reason="x",
        ),
        tenant_id="t1",
        user_id="u1",
        settings=settings,
    )
    assert trivial.reason_code == REASON_LOW_UTILITY
    assert control.reason_code != trivial.reason_code
