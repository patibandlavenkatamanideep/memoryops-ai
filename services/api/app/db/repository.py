"""Repository interface.

Every method is tenant + user scoped (invariant #1). Reads exclude non-active
status unless explicitly asked (invariant #2). This is the single place where
isolation and deletion guarantees are enforced for all callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..loops.types import LoopEvent, LoopRun
from .entities import StoredAudit, StoredMemory, StoredSettings


class Repository(ABC):
    # ── memory ───────────────────────────────────────────────────────────────
    @abstractmethod
    def create_memory(self, memory: StoredMemory) -> StoredMemory: ...

    @abstractmethod
    def get_memory(self, tenant_id: str, user_id: str, memory_id: str) -> StoredMemory | None: ...

    @abstractmethod
    def list_memories(
        self,
        tenant_id: str,
        user_id: str,
        *,
        status: str | None = None,
        memory_type: str | None = None,
        include_deleted: bool = False,
    ) -> list[StoredMemory]: ...

    @abstractmethod
    def update_memory(self, memory: StoredMemory) -> StoredMemory: ...

    @abstractmethod
    def soft_delete(self, tenant_id: str, user_id: str, memory_id: str) -> StoredMemory | None: ...

    # ── deletion compaction (v0.7, ADR-011) ───────────────────────────────────
    @abstractmethod
    def list_deleted_for_compaction(
        self, tenant_id: str, user_id: str, *, include_compacted: bool = False
    ) -> list[StoredMemory]:
        """Soft-deleted rows in scope, for the compaction worker only.

        Returns ``status='deleted'`` rows (the only rows ever eligible for
        compaction). Already-compacted rows are excluded unless
        ``include_compacted`` is set, which keeps the worker idempotent.
        """
        ...

    @abstractmethod
    def compact_deleted_memory(
        self,
        tenant_id: str,
        user_id: str,
        memory_id: str,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> StoredMemory | None:
        """Clear a soft-deleted memory's content + vector material in place.

        No-op-returns-``None`` for a missing row or any row whose status is not
        ``deleted`` (active/archived memory is never compacted, deleted memory is
        never resurrected). Preserves the governance tombstone + audit trail.
        """
        ...

    @abstractmethod
    def find_similar_active(
        self, tenant_id: str, user_id: str, content: str
    ) -> StoredMemory | None: ...

    @abstractmethod
    def retrieve_active(self, tenant_id: str, user_id: str) -> list[StoredMemory]: ...

    @abstractmethod
    def search_candidates(
        self,
        tenant_id: str,
        user_id: str,
        query_embedding: list[float],
        *,
        limit: int = 50,
    ) -> list[tuple[StoredMemory, float]]:
        """Tenant+user-scoped vector candidate fetch for hybrid retrieval.

        Returns ``(memory, vector_similarity)`` pairs for active, non-deleted rows
        ordered by similarity. On Postgres this is a pgvector ``<=>`` search with
        DB-level tenant context set; in-memory it computes cosine in Python. An
        empty ``query_embedding`` (embedding failure) returns active rows with
        similarity 0.0 so callers can degrade to keyword-only ranking.
        """
        ...

    # ── audit ────────────────────────────────────────────────────────────────
    @abstractmethod
    def add_audit(self, event: StoredAudit) -> StoredAudit: ...

    @abstractmethod
    def list_audit(
        self,
        tenant_id: str,
        user_id: str | None = None,
        *,
        memory_id: str | None = None,
        limit: int = 200,
    ) -> list[StoredAudit]: ...

    # ── settings ─────────────────────────────────────────────────────────────
    @abstractmethod
    def get_settings(self, tenant_id: str, user_id: str) -> StoredSettings: ...

    @abstractmethod
    def upsert_settings(self, settings: StoredSettings) -> StoredSettings: ...

    # ── metrics ──────────────────────────────────────────────────────────────
    @abstractmethod
    def metrics(self, tenant_id: str) -> dict: ...

    # ── loops ────────────────────────────────────────────────────────────────
    @abstractmethod
    def add_loop_run(self, run: LoopRun) -> LoopRun: ...

    @abstractmethod
    def update_loop_run(self, run: LoopRun) -> LoopRun: ...

    @abstractmethod
    def list_loop_runs(
        self,
        *,
        loop_id: str | None = None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[LoopRun]: ...

    @abstractmethod
    def add_loop_event(self, event: LoopEvent) -> LoopEvent: ...

    @abstractmethod
    def list_loop_events(
        self,
        *,
        loop_run_id: str | None = None,
        loop_id: str | None = None,
        trace_id: str | None = None,
        event_type: str | None = None,
        limit: int = 500,
    ) -> list[LoopEvent]: ...
