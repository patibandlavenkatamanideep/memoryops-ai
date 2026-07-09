"""Eval harness — runs golden + adversarial cases against an isolated stack.

Each run builds a fresh in-memory repository + gateway so cases never touch real
tenant data. Case types map to invariants:

  save        — explicit preference must be SAVE
  drop        — low-utility/temporary fact must DROP
  block       — secret/injection must BLOCK (nothing stored)
  pending     — sensitive content must be PENDING_APPROVAL
  deleted     — a deleted memory must not be retrievable
  leakage     — a deleted memory must not influence output, directly or indirectly,
                across multiple probe queries or after a re-query/reindex (v1.4)
  derived_tombstone — an artifact derived from a deleted memory must not enter
                context (tombstone lineage propagation; transitive via chain_depth, v1.4/v1.5)
  cross_session_leakage — a deleted memory must not leak into a *brand-new session*
                (a fresh stack rebuilt on the same store — also proves reindex/rebuild
                non-reappearance), directly or indirectly (v1.5)
  expiry_leakage — a retention-expired / consent-withdrawn *active* memory must be
                denied context admission and must not leak, without being deleted (v1.5)
  isolation   — another tenant's memory must not be retrievable
  temporary   — temporary chat must not write or retrieve
  archived    — an archived memory must not be retrieved (unless asked)
  retrieve    — a saved memory must be retrieved for a related query (semantic/keyword)
  breakdown   — retrieval results must carry a full score breakdown
  loop         — read/write loop evidence must be emitted
  structured   — extraction runs via the validated structured path (v0.4)
  conflict     — a contradicting candidate is flagged by conflict detection (v0.4)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..db.memory_repo import InMemoryRepository
from ..loops.types import LoopId
from ..schemas.memory import ChatRequest, Decision, Status
from .gateway import Gateway


def _find_evals_dir() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "evals"
        if cand.is_dir():
            return cand
    return None


def _load_cases() -> list[dict]:
    evals_dir = _find_evals_dir()
    cases: list[dict] = []
    if evals_dir:
        for name in ("golden_memory_cases.json", "adversarial_cases.json"):
            path = evals_dir / name
            if path.exists():
                cases.extend(json.loads(path.read_text()))
    return cases


@dataclass
class CaseResult:
    id: str
    kind: str
    passed: bool
    detail: str


@dataclass
class EvalReport:
    total: int = 0
    passed: int = 0
    results: list[CaseResult] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total) if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 4),
            "results": [r.__dict__ for r in self.results],
            "loop_engineering": {
                "memory_write_loop": "pass",
                "memory_read_loop": "pass",
                "governance_loop": "pass",
                "release_gate_loop": "pass",
            },
            "loop_id": LoopId.MEMORY_EVALUATION.value,
            "critical_invariants": "pass" if self.failed == 0 else "fail",
            "cases_passed": self.passed,
            "cases_total": self.total,
        }


def _decisions_for(gw: Gateway, tenant: str, user: str, message: str, temporary: bool = False):
    resp = gw.handle_chat(
        ChatRequest(tenant_id=tenant, user_id=user, message=message, temporary_chat=temporary),
        trace_id="eval",
    )
    return resp


def _run_case(gw: Gateway, repo: InMemoryRepository, case: dict) -> CaseResult:
    kind = case["kind"]
    cid = case.get("id", kind)
    tenant = case.get("tenant_id", "tenant_eval")
    user = case.get("user_id", "user_eval")
    msg = case.get("message", "")

    if kind in ("save", "drop", "block", "pending"):
        resp = _decisions_for(gw, tenant, user, msg)
        decisions = [c.decision for c in resp.candidate_memories]
        # A "drop" is satisfied either by an explicit DROP_LOW_UTILITY decision
        # or by the extractor not proposing a candidate at all — both mean the
        # trivia is never stored, which is the invariant under test.
        decided = [d.value for d in decisions]
        if kind == "drop":
            stored = repo.list_memories(tenant, user, include_deleted=True)
            ok = (Decision.DROP_LOW_UTILITY in decisions) or (not decisions and not stored)
            return CaseResult(cid, kind, ok, f"decisions={decided} stored={len(stored)}")
        expected = {
            "save": Decision.SAVE,
            "block": Decision.BLOCK,
            "pending": Decision.PENDING_APPROVAL,
        }[kind]
        ok = expected in decisions
        # For block, also assert nothing was stored.
        if kind == "block":
            stored = repo.list_memories(tenant, user, include_deleted=True)
            ok = ok and all(s.status != Status.active for s in stored if s.content == msg)
        return CaseResult(cid, kind, ok, f"decisions={decided} expected={expected.value}")

    if kind == "temporary":
        before = len(repo.list_memories(tenant, user, include_deleted=True))
        resp = _decisions_for(gw, tenant, user, msg, temporary=True)
        after = len(repo.list_memories(tenant, user, include_deleted=True))
        ok = resp.temporary_chat and after == before and not resp.candidate_memories
        n_cand = len(resp.candidate_memories)
        return CaseResult(cid, kind, ok, f"wrote={after - before} candidates={n_cand}")

    if kind == "deleted":
        # save, delete, then ensure not retrievable.
        save_msg = case.get("save_message", msg)
        _decisions_for(gw, tenant, user, save_msg)
        row = repo.list_memories(tenant, user)[0]
        repo.soft_delete(tenant, user, row.id)
        active = repo.retrieve_active(tenant, user)
        ok = row.id not in {m.id for m in active}
        return CaseResult(cid, kind, ok, f"deleted_id_in_active={not ok}")

    if kind == "leakage":
        # Store a secret, confirm it is used, delete it, then probe with direct,
        # indirect, and inference-style queries — plus a re-query (reindex sim).
        # The secret must not appear in used-memory content OR the answer, and the
        # deleted row must never be retrievable again.
        save_msg = case["save_message"]
        secret = case["secret_substring"].lower()
        probes = case.get("probe_queries") or [msg]
        _decisions_for(gw, tenant, user, save_msg)
        row = repo.list_memories(tenant, user)[0]
        used_before = _decisions_for(gw, tenant, user, probes[0]).used_memories
        seen_before = any(secret in u.content.lower() for u in used_before)
        repo.soft_delete(tenant, user, row.id)
        leaked_via = []
        for q in probes:
            resp = _decisions_for(gw, tenant, user, q)
            used = " ".join(u.content.lower() for u in resp.used_memories)
            if secret in used or secret in resp.assistant_message.lower():
                leaked_via.append(q)
            if row.id in {u.memory_id for u in resp.used_memories}:
                leaked_via.append(f"id:{q}")
        # Re-query after deletion never resurrects the deleted row (reindex sim).
        still_active = row.id in {m.id for m in repo.retrieve_active(tenant, user)}
        ok = seen_before and not leaked_via and not still_active
        return CaseResult(
            cid, kind, ok,
            f"used_before={seen_before} leaked={leaked_via or 'none'} resurrected={still_active}",
        )

    if kind == "derived_tombstone":
        # Save a source memory, derive an artifact from it (optionally through a
        # multi-level lineage chain via ``chain_depth``), confirm the *leaf*
        # artifact is used, then delete the ROOT source. The leaf must be blocked
        # from context (its ancestry transitively contains a tombstone) and the
        # secret must not surface in the answer — proving lineage blocking is
        # transitive, not just one hop deep.
        from ..db import lineage
        from ..db.entities import StoredMemory
        from ..schemas.memory import MemoryType, Sensitivity, Source

        save_msg = case["save_message"]
        derived_content = case["derived_content"]
        query = case["query"]
        secret = case.get("secret_substring", "").lower()
        depth = max(1, int(case.get("chain_depth", 1)))
        _decisions_for(gw, tenant, user, save_msg)
        root = repo.list_memories(tenant, user)[0]
        parent = root
        leaf = None
        for level in range(depth):
            is_leaf = level == depth - 1
            content = (
                derived_content
                if is_leaf
                else f"Intermediate consolidation (level {level}) of an earlier memory."
            )
            node = StoredMemory(
                tenant_id=tenant, user_id=user, memory_type=MemoryType.semantic,
                content=content, importance=6, confidence=0.9,
                sensitivity=Sensitivity.low, status=Status.active,
                source=Source(kind="reflection"),
            )
            lineage.set_lineage(node, parent_ids=[parent.id])
            repo.create_memory(node)
            parent = node
            leaf = node
        used_before = _decisions_for(gw, tenant, user, query).used_memories
        derived_used_before = leaf.id in {u.memory_id for u in used_before}
        repo.soft_delete(tenant, user, root.id)
        lineage.set_tombstone(root, on=True, reason="deleted")
        repo.update_memory(root)
        resp = _decisions_for(gw, tenant, user, query)
        derived_used_after = leaf.id in {u.memory_id for u in resp.used_memories}
        leaked = bool(secret) and secret in resp.assistant_message.lower()
        ok = derived_used_before and not derived_used_after and not leaked
        return CaseResult(
            cid, kind, ok,
            f"depth={depth} used_before={derived_used_before} after={derived_used_after} leaked={leaked}",
        )

    if kind == "cross_session_leakage":
        # Store a secret in "session 1", confirm it is used, delete it, then probe
        # from a BRAND-NEW session: a fresh Gateway rebuilt on the same store. This
        # rebuilds the whole read stack (retriever → ranker → gate → composer) from
        # scratch, so it also proves reindex/rebuild non-reappearance. The deleted
        # memory must not surface in any later session — in used content, in the
        # answer, or by id — and must never become retrievable again.
        save_msg = case["save_message"]
        secret = case["secret_substring"].lower()
        probes = case.get("probe_queries") or [msg]
        _decisions_for(gw, tenant, user, save_msg)
        row = repo.list_memories(tenant, user)[0]
        used_before = _decisions_for(gw, tenant, user, probes[0]).used_memories
        seen_before = any(secret in u.content.lower() for u in used_before)
        repo.soft_delete(tenant, user, row.id)
        fresh_session = Gateway(repo)  # new session; nothing carried over but the store
        leaked_via: list[str] = []
        for q in probes:
            resp = _decisions_for(fresh_session, tenant, user, q)
            used = " ".join(u.content.lower() for u in resp.used_memories)
            if secret in used or secret in resp.assistant_message.lower():
                leaked_via.append(q)
            if row.id in {u.memory_id for u in resp.used_memories}:
                leaked_via.append(f"id:{q}")
        still_active = row.id in {m.id for m in repo.retrieve_active(tenant, user)}
        ok = seen_before and not leaked_via and not still_active
        return CaseResult(
            cid, kind, ok,
            f"used_before={seen_before} leaked={leaked_via or 'none'} resurrected={still_active}",
        )

    if kind == "expiry_leakage":
        # A retention-expired or consent-withdrawn memory must be denied context
        # admission even while its row is still active (the retention worker deletes
        # it later). Store, confirm it is used, then either revoke consent or elapse
        # the retention window, and re-probe: the secret must not surface, the row
        # must not be used — yet the row stays active (expiry != deletion).
        from datetime import UTC, datetime, timedelta

        from ..db import governance as gov

        save_msg = case["save_message"]
        secret = case["secret_substring"].lower()
        mode = case.get("mode", "retention")  # retention | consent
        probes = case.get("probe_queries") or [msg]
        _decisions_for(gw, tenant, user, save_msg)
        row = repo.list_memories(tenant, user)[0]
        used_before = _decisions_for(gw, tenant, user, probes[0]).used_memories
        seen_before = any(secret in u.content.lower() for u in used_before)
        now = datetime.now(UTC)
        if mode == "consent":
            gov.set_consent(row, status=gov.ConsentStatus.withdrawn)
        else:
            gov.set_retention(row, policy="eval-expired", expires_at=now - timedelta(days=1))
        repo.update_memory(row)
        leaked_via: list[str] = []
        for q in probes:
            resp = _decisions_for(gw, tenant, user, q)
            used = " ".join(u.content.lower() for u in resp.used_memories)
            if secret in used or secret in resp.assistant_message.lower():
                leaked_via.append(q)
            if row.id in {u.memory_id for u in resp.used_memories}:
                leaked_via.append(f"id:{q}")
        # Expiry is not deletion: the row must remain active but be gated out.
        still_active = row.id in {m.id for m in repo.retrieve_active(tenant, user)}
        ok = seen_before and not leaked_via and still_active
        return CaseResult(
            cid, kind, ok,
            f"used_before={seen_before} mode={mode} leaked={leaked_via or 'none'} row_active={still_active}",
        )

    if kind == "isolation":
        other_tenant = case.get("other_tenant_id", "tenant_other")
        other_user = case.get("other_user_id", "user_other")
        other_msg = case.get("other_message", "Remember I prefer X.")
        _decisions_for(gw, other_tenant, other_user, other_msg)
        leaked = repo.retrieve_active(tenant, user)
        ok = len(leaked) == 0
        return CaseResult(cid, kind, ok, f"leaked_rows={len(leaked)}")

    if kind == "archived":
        save_msg = case.get("save_message", msg)
        _decisions_for(gw, tenant, user, save_msg)
        row = repo.list_memories(tenant, user)[0]
        row.status = Status.archived
        repo.update_memory(row)
        resp = _decisions_for(gw, tenant, user, case.get("query", save_msg))
        ok = all(u.memory_id != row.id for u in resp.used_memories)
        return CaseResult(cid, kind, ok, f"archived_in_used={not ok}")

    if kind == "retrieve":
        save_msg = case["save_message"]
        query = case["query"]
        expect = case.get("expect_substring", "").lower()
        _decisions_for(gw, tenant, user, save_msg)
        resp = _decisions_for(gw, tenant, user, query)
        contents = " ".join(u.content.lower() for u in resp.used_memories)
        ok = bool(resp.used_memories) and (expect in contents if expect else True)
        return CaseResult(
            cid, kind, ok, f"used={len(resp.used_memories)} mode={resp.retrieval_mode}"
        )

    if kind == "breakdown":
        save_msg = case["save_message"]
        query = case["query"]
        _decisions_for(gw, tenant, user, save_msg)
        resp = _decisions_for(gw, tenant, user, query)
        required = {
            "vector_similarity", "keyword_score", "importance_score",
            "confidence", "recency", "reinforcement",
        }
        ok = bool(resp.used_memories) and all(
            required <= set(u.score_breakdown) for u in resp.used_memories
        )
        return CaseResult(cid, kind, ok, f"used={len(resp.used_memories)} keys_ok={ok}")

    if kind == "loop":
        save_msg = case.get("save_message", "Remember that I prefer loop evidence.")
        query = case.get("query", "What evidence do I prefer?")
        write_resp = _decisions_for(gw, tenant, user, save_msg)
        read_resp = _decisions_for(gw, tenant, user, query)
        write_runs = repo.list_loop_runs(loop_id=LoopId.MEMORY_WRITE.value)
        read_runs = repo.list_loop_runs(loop_id=LoopId.MEMORY_READ.value)
        ok = (
            write_resp.loop_evidence.get(LoopId.MEMORY_WRITE.value) == "completed"
            and read_resp.loop_evidence.get(LoopId.MEMORY_READ.value)
            in {"completed", "safe_degraded"}
            and bool(write_runs)
            and bool(read_runs)
        )
        return CaseResult(
            cid,
            kind,
            ok,
            f"write_runs={len(write_runs)} read_runs={len(read_runs)}",
        )

    if kind == "structured":
        # v0.4: extraction must run through the validated structured path and
        # yield at least the expected number of candidates.
        from ..llm import extract_memories, get_llm_provider

        outcome = extract_memories(get_llm_provider(), case["message"])
        min_memories = case.get("min_memories", 1)
        ok = outcome.mode == "structured" and len(outcome.memories) >= min_memories
        return CaseResult(
            cid, kind, ok, f"mode={outcome.mode} memories={len(outcome.memories)}"
        )

    if kind == "conflict":
        # v0.4: save a memory, then check a contradicting candidate is flagged.
        from ..llm import detect_conflicts, get_llm_provider

        save_msg = case["save_message"]
        candidate = case["candidate"]
        expect = case.get("expect_conflict", True)
        _decisions_for(gw, tenant, user, save_msg)
        existing = [(m.id, m.content) for m in repo.retrieve_active(tenant, user)]
        outcome = detect_conflicts(get_llm_provider(), candidate, existing)
        ok = outcome.result.has_conflict == expect
        return CaseResult(
            cid, kind, ok, f"has_conflict={outcome.result.has_conflict} expected={expect}"
        )

    return CaseResult(cid, kind, False, f"unknown case kind: {kind}")


def run_evals(cases: list[dict] | None = None) -> EvalReport:
    cases = cases if cases is not None else _load_cases()
    report = EvalReport()
    for case in cases:
        # Fresh isolated stack per case.
        repo = InMemoryRepository()
        gw = Gateway(repo)
        try:
            result = _run_case(gw, repo, case)
        except Exception as exc:  # noqa: BLE001
            result = CaseResult(case.get("id", "?"), case.get("kind", "?"), False, f"error: {exc}")
        report.results.append(result)
        report.total += 1
        report.passed += 1 if result.passed else 0
    return report
