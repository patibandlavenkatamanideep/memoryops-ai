"""Vector / content purge verification (v0.7, ADR-011).

After a soft-deleted memory is compacted, this module proves — at the access paths
a caller could actually reach — that the memory is gone *and* that its retrievable
content + vector material were really cleared. It is the evidence half of the
compaction story: compaction does the clearing, verification confirms it.

Honest scope: this verifies **application-level retrieval exclusion** and
**repository-level content/vector material clearing**. It does not (and does not
claim to) prove database-page or ANN-index physical byte reclamation — that is the
storage engine's job and is documented separately (see docs/vector-purge-verification.md).

The verifier is **fail-closed**: any reachable surface, any material left intact,
a missing tombstone, or an error in the verification path itself all yield
``fail`` — never a silent ``pass``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..db.repository import Repository
from .schemas import PurgeVerification


@dataclass
class PurgeCheck:
    """Content-free verification outcome for a single memory (ids/flags only)."""

    memory_id: str
    result: str  # PurgeVerification value
    reachable_surfaces: list[str] = field(default_factory=list)
    content_cleared: bool = False
    vector_cleared: bool = False
    tombstone_present: bool = False
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.result == PurgeVerification.passed.value


# The reachable read surfaces a deleted/compacted id must never appear in. An
# empty query embedding makes the vector path degrade to "active rows at
# similarity 0" — exactly the set a purged id must stay out of.
def _reachable_surfaces(
    repo: Repository, tenant_id: str, user_id: str, memory_id: str
) -> list[str]:
    active_ids = {m.id for m in repo.retrieve_active(tenant_id, user_id)}
    listed_ids = {m.id for m in repo.list_memories(tenant_id, user_id)}
    candidate_ids = {m.id for m, _ in repo.search_candidates(tenant_id, user_id, [])}
    return [
        name
        for name, ids in (
            ("active_retrieval", active_ids),
            ("listing", listed_ids),
            ("vector_candidates", candidate_ids),
        )
        if memory_id in ids
    ]


def verify_purged(
    repo: Repository,
    *,
    tenant_id: str,
    user_id: str,
    memory_id: str,
    vector_supported: bool = True,
) -> PurgeCheck:
    """Verify a compacted memory is unreachable and its material was cleared.

    Returns ``pass`` only when the id is absent from every reachable surface, the
    governance tombstone is still present, content is cleared, and (when the
    backend supports it) vector material is cleared. Anything else is ``fail``.
    ``not_supported`` is reserved for a backend that cannot clear vector material
    at all; both shipped backends can, so it is not returned in practice.
    """
    try:
        surfaces = _reachable_surfaces(repo, tenant_id, user_id, memory_id)
        # get_memory returns the row regardless of status, so we can inspect the
        # tombstone and confirm the payload is actually empty.
        row = repo.get_memory(tenant_id, user_id, memory_id)
        tombstone_present = row is not None
        content_cleared = bool(row) and not (row.content or "").strip()
        vector_cleared = bool(row) and not row.embedding

        check = PurgeCheck(
            memory_id=memory_id,
            result=PurgeVerification.failed.value,
            reachable_surfaces=surfaces,
            content_cleared=content_cleared,
            vector_cleared=vector_cleared,
            tombstone_present=tombstone_present,
        )

        if surfaces:
            check.reason = "compacted memory still reachable in a retrieval surface"
            return check
        if not tombstone_present:
            check.reason = "governance tombstone missing after compaction"
            return check
        if not content_cleared:
            check.reason = "retrievable content not cleared"
            return check
        if not vector_supported:
            check.result = PurgeVerification.not_supported.value
            check.reason = "backend does not support vector material clearing"
            return check
        if not vector_cleared:
            check.reason = "vector material not cleared"
            return check

        check.result = PurgeVerification.passed.value
        check.reason = "unreachable; content + vector material cleared; tombstone preserved"
        return check
    except Exception as exc:  # noqa: BLE001 — fail closed, never pass on error
        return PurgeCheck(
            memory_id=memory_id,
            result=PurgeVerification.failed.value,
            reason=f"verification path error: {type(exc).__name__}",
        )
