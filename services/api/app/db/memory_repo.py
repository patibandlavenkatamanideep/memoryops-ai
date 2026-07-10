"""In-memory repository — default backend for dev/tests (no infra required).

Mirrors the exact query semantics the Postgres backend must honor: tenant+user
scoping on every read, deleted rows excluded from retrieval, append-only audit.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..loops.metrics import summarize_loop_runs
from ..loops.types import LoopEvent, LoopRun
from .entities import (
    StoredAudit,
    StoredMemory,
    StoredSettings,
    WorkerLease,
    WorkerRunRecord,
    apply_compaction,
    is_compacted,
)
from .repository import Repository
from .vector import InMemoryVectorIndex, VectorIndex

_ACTIVE = "active"
_DELETED = "deleted"


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


class InMemoryRepository(Repository):
    def __init__(self, vector_index: VectorIndex | None = None) -> None:
        self._memories: dict[str, StoredMemory] = {}
        self._audit: list[StoredAudit] = []
        self._settings: dict[tuple[str, str], StoredSettings] = {}
        self._loop_runs: dict[str, LoopRun] = {}
        self._loop_events: list[LoopEvent] = []
        self._leases: dict[str, WorkerLease] = {}
        self._worker_runs: list[WorkerRunRecord] = []
        # The pluggable vector-search seam (v1.7, ADR-021). Defaults to the
        # dependency-free cosine index; an operator can inject an external backend.
        self._vectors: VectorIndex = vector_index or InMemoryVectorIndex()

    # ── memory ───────────────────────────────────────────────────────────────
    def create_memory(self, memory: StoredMemory) -> StoredMemory:
        if not memory.source:  # provenance is mandatory (invariant #3)
            raise ValueError("memory.source (provenance) is required")
        self._memories[memory.id] = memory
        self._vectors.upsert(memory.tenant_id, memory.user_id, memory.id, memory.embedding or [])
        return memory

    def _scoped(self, tenant_id: str, user_id: str) -> list[StoredMemory]:
        # Tenant + user isolation enforced here (invariant #1).
        return [
            m
            for m in self._memories.values()
            if m.tenant_id == tenant_id and m.user_id == user_id
        ]

    def get_memory(self, tenant_id: str, user_id: str, memory_id: str) -> StoredMemory | None:
        m = self._memories.get(memory_id)
        if m and m.tenant_id == tenant_id and m.user_id == user_id:
            return m
        return None

    def list_memories(
        self,
        tenant_id: str,
        user_id: str,
        *,
        status: str | None = None,
        memory_type: str | None = None,
        include_deleted: bool = False,
    ) -> list[StoredMemory]:
        rows = self._scoped(tenant_id, user_id)
        if not include_deleted:
            rows = [m for m in rows if m.status.value != _DELETED]
        if status:
            rows = [m for m in rows if m.status.value == status]
        if memory_type:
            rows = [m for m in rows if m.memory_type.value == memory_type]
        return sorted(rows, key=lambda m: m.created_at, reverse=True)

    def update_memory(self, memory: StoredMemory) -> StoredMemory:
        memory.updated_at = datetime.now(UTC)
        self._memories[memory.id] = memory
        # Keep the vector index in sync: a non-active row is not searchable.
        if memory.status.value == _ACTIVE:
            self._vectors.upsert(memory.tenant_id, memory.user_id, memory.id, memory.embedding or [])
        else:
            self._vectors.delete(memory.tenant_id, memory.user_id, memory.id)
        return memory

    def soft_delete(self, tenant_id: str, user_id: str, memory_id: str) -> StoredMemory | None:
        m = self.get_memory(tenant_id, user_id, memory_id)
        if not m:
            return None
        from ..schemas.memory import Status

        m.status = Status.deleted
        m.deleted_at = datetime.now(UTC)
        m.updated_at = m.deleted_at
        # Deletion (#2): the vector is removed so it can never be a candidate again.
        self._vectors.delete(tenant_id, user_id, memory_id)
        return m

    def list_deleted_for_compaction(
        self, tenant_id: str, user_id: str, *, include_compacted: bool = False
    ) -> list[StoredMemory]:
        rows = [m for m in self._scoped(tenant_id, user_id) if m.status.value == _DELETED]
        if not include_compacted:
            rows = [m for m in rows if not is_compacted(m)]
        return sorted(rows, key=lambda m: m.deleted_at or m.created_at, reverse=True)

    def compact_deleted_memory(
        self,
        tenant_id: str,
        user_id: str,
        memory_id: str,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> StoredMemory | None:
        m = self.get_memory(tenant_id, user_id, memory_id)
        # Only deleted rows are ever compacted (never resurrect, never touch active).
        if not m or m.status.value != _DELETED:
            return None
        apply_compaction(m, reason=reason, now=now or datetime.now(UTC))
        self._memories[m.id] = m
        self._vectors.delete(tenant_id, user_id, memory_id)  # vector material cleared
        return m

    def find_similar_active(
        self, tenant_id: str, user_id: str, content: str
    ) -> StoredMemory | None:
        target = _norm(content)
        for m in self._scoped(tenant_id, user_id):
            if m.status.value == _ACTIVE and _norm(m.content) == target:
                return m
        return None

    def retrieve_active(self, tenant_id: str, user_id: str) -> list[StoredMemory]:
        # Only active rows are ever retrievable (invariant #2).
        return [m for m in self._scoped(tenant_id, user_id) if m.status.value == _ACTIVE]

    def search_candidates(
        self,
        tenant_id: str,
        user_id: str,
        query_embedding: list[float],
        *,
        limit: int = 50,
    ) -> list[tuple[StoredMemory, float]]:
        # Similarity is delegated to the pluggable VectorIndex (v1.7, ADR-021); the
        # repository stays authoritative for which rows are candidates. Active rows
        # the index does not score (no vector, or embedding failure) are still
        # returned at 0.0 so callers degrade to keyword-only ranking (invariant #4).
        active = self.retrieve_active(tenant_id, user_id)
        if not query_embedding:
            return [(m, 0.0) for m in active][:limit]
        ranked = {
            match.memory_id: match.score
            for match in self._vectors.query(
                tenant_id, user_id, query_embedding, limit=max(limit, len(active))
            )
        }
        scored = [(m, ranked.get(m.id, 0.0)) for m in active]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]

    # ── audit ────────────────────────────────────────────────────────────────
    def add_audit(self, event: StoredAudit) -> StoredAudit:
        self._audit.append(event)  # append-only (invariant #7)
        return event

    def list_audit(
        self,
        tenant_id: str,
        user_id: str | None = None,
        *,
        memory_id: str | None = None,
        limit: int = 200,
    ) -> list[StoredAudit]:
        rows = [e for e in self._audit if e.tenant_id == tenant_id]
        if user_id:
            rows = [e for e in rows if e.user_id == user_id]
        if memory_id:
            rows = [e for e in rows if e.memory_id == memory_id]
        return sorted(rows, key=lambda e: e.created_at, reverse=True)[:limit]

    # ── worker runtime (v0.8) ──────────────────────────────────────────────────
    def try_acquire_lease(
        self, key: str, owner: str, *, now: datetime, expires_at: datetime
    ) -> bool:
        existing = self._leases.get(key)
        if existing and existing.expires_at > now and existing.owner != owner:
            return False  # another owner holds a live lease → duplicate prevented
        self._leases[key] = WorkerLease(
            key=key, owner=owner, acquired_at=now, expires_at=expires_at
        )
        return True

    def renew_lease(self, key: str, owner: str, *, expires_at: datetime) -> bool:
        existing = self._leases.get(key)
        if not existing or existing.owner != owner:
            return False
        existing.expires_at = expires_at
        return True

    def release_lease(self, key: str, owner: str) -> None:
        existing = self._leases.get(key)
        if existing and existing.owner == owner:
            del self._leases[key]

    def get_lease(self, key: str) -> WorkerLease | None:
        return self._leases.get(key)

    def add_worker_run(self, record: WorkerRunRecord) -> WorkerRunRecord:
        self._worker_runs.append(record)
        return record

    def list_worker_runs(
        self,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[WorkerRunRecord]:
        rows = list(self._worker_runs)
        if tenant_id:
            rows = [r for r in rows if r.tenant_id == tenant_id]
        if user_id:
            rows = [r for r in rows if r.user_id == user_id]
        if status:
            rows = [r for r in rows if r.status == status]
        return sorted(rows, key=lambda r: r.started_at, reverse=True)[:limit]

    # ── settings ─────────────────────────────────────────────────────────────
    def get_settings(self, tenant_id: str, user_id: str) -> StoredSettings:
        return self._settings.get(
            (tenant_id, user_id), StoredSettings(tenant_id=tenant_id, user_id=user_id)
        )

    def upsert_settings(self, settings: StoredSettings) -> StoredSettings:
        self._settings[(settings.tenant_id, settings.user_id)] = settings
        return settings

    # ── metrics ──────────────────────────────────────────────────────────────
    def metrics(self, tenant_id: str) -> dict:
        rows = [m for m in self._memories.values() if m.tenant_id == tenant_id]
        by_status: dict[str, int] = {}
        for m in rows:
            by_status[m.status.value] = by_status.get(m.status.value, 0) + 1
        audit = [e for e in self._audit if e.tenant_id == tenant_id]
        by_action: dict[str, int] = {}
        for e in audit:
            by_action[e.action] = by_action.get(e.action, 0) + 1
        return {
            "total_memories": len(rows),
            "by_status": by_status,
            "audit_events": len(audit),
            "by_action": by_action,
            "loops": summarize_loop_runs(
                [r for r in self._loop_runs.values() if r.tenant_id in (tenant_id, None)]
            ),
        }

    # ── loops ────────────────────────────────────────────────────────────────
    def add_loop_run(self, run: LoopRun) -> LoopRun:
        self._loop_runs[run.id] = run
        return run

    def update_loop_run(self, run: LoopRun) -> LoopRun:
        self._loop_runs[run.id] = run
        return run

    def list_loop_runs(
        self,
        *,
        loop_id: str | None = None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[LoopRun]:
        rows = list(self._loop_runs.values())
        if loop_id:
            rows = [r for r in rows if r.loop_id.value == loop_id]
        if trace_id:
            rows = [r for r in rows if r.trace_id == trace_id]
        if tenant_id:
            rows = [r for r in rows if r.tenant_id == tenant_id]
        if user_id:
            rows = [r for r in rows if r.user_id == user_id]
        if status:
            rows = [r for r in rows if r.status.value == status]
        return sorted(rows, key=lambda r: r.started_at, reverse=True)[:limit]

    def add_loop_event(self, event: LoopEvent) -> LoopEvent:
        self._loop_events.append(event)
        return event

    def list_loop_events(
        self,
        *,
        loop_run_id: str | None = None,
        loop_id: str | None = None,
        trace_id: str | None = None,
        event_type: str | None = None,
        limit: int = 500,
    ) -> list[LoopEvent]:
        rows = self._loop_events
        if loop_run_id:
            rows = [e for e in rows if e.loop_run_id == loop_run_id]
        if loop_id:
            rows = [e for e in rows if e.loop_id.value == loop_id]
        if trace_id:
            rows = [e for e in rows if e.trace_id == trace_id]
        if event_type:
            rows = [e for e in rows if e.event_type == event_type]
        return sorted(rows, key=lambda e: e.created_at, reverse=True)[:limit]
