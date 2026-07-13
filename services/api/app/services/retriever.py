"""Retriever — hybrid candidate fetch (ADR-002, ADR-006).

v0.3: vector candidates come from the repository's tenant-scoped
``search_candidates`` (real pgvector on Postgres, cosine in-memory otherwise);
keyword overlap is computed on the returned rows. Deleted/pending/wrong-tenant
rows are never returned because the repository filters them at the source.

If embedding the query fails, retrieval degrades to keyword-only ranking and
reports ``retrieval_mode="fallback"`` (invariant #4, graceful degradation).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.logging import get_logger
from ..db.entities import StoredMemory
from ..db.repository import Repository
from ..embeddings import embed
from .keyword_scoring import bm25_scores

logger = get_logger("memoryops.retriever")


@dataclass
class ScoredCandidate:
    memory: StoredMemory
    semantic: float  # vector similarity (cosine)
    keyword: float


@dataclass
class RetrievalResult:
    candidates: list[ScoredCandidate]
    mode: str  # "hybrid" | "fallback"


class Retriever:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def retrieve(self, tenant_id: str, user_id: str, query: str) -> RetrievalResult:
        # Embedding the query is the only step that can fail; degrade to keyword.
        mode = "hybrid"
        try:
            q_embedding = embed(query)
        except Exception:  # noqa: BLE001 — graceful degradation
            logger.warning(
                "query embedding failed; keyword-only retrieval",
                extra={"event": "retrieval_fallback"},
            )
            q_embedding = []
            mode = "fallback"

        pairs = self._repo.search_candidates(tenant_id, user_id, q_embedding)
        if not pairs:
            return RetrievalResult(candidates=[], mode=mode)

        # BM25 keyword relevance over the candidate set (stopword-aware, term-weighted),
        # normalized to [0, 1] so it blends with the [0, 1] semantic score in the ranker.
        keyword_scores = bm25_scores(query, [m.content for m, _ in pairs])
        scored = [
            ScoredCandidate(memory=memory, semantic=similarity, keyword=keyword_scores[i])
            for i, (memory, similarity) in enumerate(pairs)
        ]
        return RetrievalResult(candidates=scored, mode=mode)
