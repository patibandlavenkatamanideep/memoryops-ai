"""MemoryOps adapters — S0 (governed) and S0-U (governance-disabled).

Both drive the **real** MemoryOps pipeline in-process over its actual HTTP surface
(FastAPI `TestClient`), so the study measures the shipped system, not a re-implementation.
The only difference between S0 and S0-U is the governance profile the process runs
under (`MEMORYOPS_GOVERNANCE_PROFILE=full` vs `disabled`) — same extractor, embeddings,
store, retrieval, top-k, prompt, LLM, and temperature (protocol §3).

Because the app resolves settings + repository from process-global caches, an adapter
configures the process and rebuilds a fresh client on `reset()`; the runner drives one
system at a time (reset → run its cases → next system), never two profiles at once.

This module is *experiment tooling*: it bridges the repo-root harness to the frozen
`services/api` app via a guarded ``sys.path`` insert (the app itself is untouched).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .types import (
    Capability,
    EvidenceResult,
    ForgetResult,
    IngestResult,
    MemoryRef,
    OpStatus,
    QueryResult,
    Scope,
    UpdateResult,
)

# Bridge to the frozen app package (services/api) without touching it.
_API = Path(__file__).resolve().parents[2] / "services" / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))


class MemoryOpsAdapter:
    """Drive MemoryOps under a fixed governance profile. Use ``s0()`` / ``s0u()``."""

    def __init__(self, *, profile: str, name: str) -> None:
        assert profile in ("full", "disabled")
        self._profile = profile
        self.name = name
        self._client = None
        self.reset()

    # ── lifecycle ────────────────────────────────────────────────────────────
    def _configure_process(self) -> None:
        os.environ["MEMORYOPS_STORAGE"] = "memory"
        os.environ["MEMORYOPS_GOVERNANCE_PROFILE"] = self._profile
        os.environ["MEMORYOPS_RATE_LIMIT_ENABLED"] = "false"  # benchmark, not a demo
        from app import deps
        from app.core import config
        from app.db import factory

        config.get_settings.cache_clear()
        factory.get_repository.cache_clear()
        deps.gateway.cache_clear()
        deps.audit_service.cache_clear()

    def reset(self) -> None:
        self._configure_process()
        from fastapi.testclient import TestClient

        from app.main import app

        self._client = TestClient(app)

    def capabilities(self) -> set[Capability]:
        # MemoryOps exposes every operation; S0-U differs in *behavior*, not surface.
        return set(Capability)

    # ── operations ───────────────────────────────────────────────────────────
    def ingest(self, scope: Scope, message: str) -> IngestResult:
        before = self._memory_ids(scope)
        r = self._client.post(
            "/api/chat",
            json={"tenant_id": scope.tenant_id, "user_id": scope.user_id, "message": message},
        )
        if r.status_code != 200:
            return IngestResult(status=OpStatus.ERROR, detail=f"chat {r.status_code}")
        created = sorted(self._memory_ids(scope) - before)
        return IngestResult(status=OpStatus.OK, memory_ids=created)

    def query(self, scope: Scope, question: str) -> QueryResult:
        r = self._client.post(
            "/api/chat",
            json={"tenant_id": scope.tenant_id, "user_id": scope.user_id, "message": question},
        )
        if r.status_code != 200:
            return QueryResult(status=OpStatus.ERROR, detail=f"chat {r.status_code}")
        data = r.json()
        used = data.get("used_memories", []) or []
        return QueryResult(
            status=OpStatus.OK,
            answer=data.get("assistant_message", "") or "",
            used_memory_ids=[m["memory_id"] for m in used],
            retrieved=[
                MemoryRef(memory_id=m["memory_id"], content=m.get("content"), score=m.get("score"))
                for m in used
            ],
        )

    def forget(self, scope: Scope, memory_id: str) -> ForgetResult:
        r = self._client.request(
            "DELETE",
            f"/api/memories/{memory_id}",
            json={"tenant_id": scope.tenant_id, "user_id": scope.user_id},
        )
        if r.status_code == 200:
            return ForgetResult(status=OpStatus.OK)
        return ForgetResult(status=OpStatus.ERROR, detail=f"delete {r.status_code}")

    def update(self, scope: Scope, memory_id: str, content: str) -> UpdateResult:
        r = self._client.patch(
            f"/api/memories/{memory_id}",
            json={"tenant_id": scope.tenant_id, "user_id": scope.user_id, "content": content},
        )
        if r.status_code == 200:
            return UpdateResult(status=OpStatus.OK)
        return UpdateResult(status=OpStatus.ERROR, detail=f"patch {r.status_code}")

    def export_evidence(self, scope: Scope) -> EvidenceResult:
        r = self._client.get(
            "/api/evidence/policy",
            params={"tenant_id": scope.tenant_id, "user_id": scope.user_id},
        )
        if r.status_code == 200:
            return EvidenceResult(status=OpStatus.OK, available=True, payload=r.json())
        return EvidenceResult(status=OpStatus.ERROR, detail=f"evidence {r.status_code}")

    # ── helpers ──────────────────────────────────────────────────────────────
    def _memory_ids(self, scope: Scope) -> set[str]:
        r = self._client.get(
            "/api/memories",
            params={"tenant_id": scope.tenant_id, "user_id": scope.user_id},
        )
        if r.status_code != 200:
            return set()
        return {m["id"] for m in r.json()}


def s0() -> MemoryOpsAdapter:
    """Governed MemoryOps — the system under study."""
    return MemoryOpsAdapter(profile="full", name="S0")


def s0u() -> MemoryOpsAdapter:
    """Governance-disabled MemoryOps — the mechanism-matched comparator (H2/H4)."""
    return MemoryOpsAdapter(profile="disabled", name="S0-U")
