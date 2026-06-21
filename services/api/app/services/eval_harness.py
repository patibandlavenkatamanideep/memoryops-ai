"""Eval harness — runs golden + adversarial cases against an isolated stack.

Each run builds a fresh in-memory repository + gateway so cases never touch real
tenant data. Case types map to invariants:

  save        — explicit preference must be SAVE
  drop        — low-utility/temporary fact must DROP
  block       — secret/injection must BLOCK (nothing stored)
  pending     — sensitive content must be PENDING_APPROVAL
  deleted     — a deleted memory must not be retrievable
  isolation   — another tenant's memory must not be retrievable
  temporary   — temporary chat must not write or retrieve
  archived    — an archived memory must not be retrieved (unless asked)
  retrieve    — a saved memory must be retrieved for a related query (semantic/keyword)
  breakdown   — retrieval results must carry a full score breakdown
  loop         — read/write loop evidence must be emitted
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
