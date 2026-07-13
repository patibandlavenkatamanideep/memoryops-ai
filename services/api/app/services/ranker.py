"""Ranker — weighted blend of retrieval + memory signals (ADR-002, ADR-006).

final_score = w_semantic·vector_similarity + w_keyword·keyword + w_importance·importance
            + w_confidence·confidence + w_recency·recency + w_reinforcement·reinforcement

The weights are **configuration, not magic constants** (P3.2): the defaults
(0.35/0.20/0.15/0.10/0.10/0.10) prioritize semantic + keyword relevance and are the
documented starting point, tunable per deployment via `MEMORYOPS_RANK_W_*` (and a
per-tenant surface later). Weights are normalized to sum to 1 at load, so the score
stays in [0,1] and the score floor keeps a stable meaning. Each ranked memory carries
a ``score_breakdown`` of the raw [0,1] signals so the API/UI can explain exactly why
a memory surfaced (invariant #8). If this formula changes, docs/api-contracts.md and
docs/architecture.md must be updated (enforced by the PR Invariant Evidence Gate).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..core.config import Settings, get_settings
from .retriever import ScoredCandidate

_RECENCY_HALFLIFE_DAYS = 30.0


@dataclass(frozen=True)
class RankerWeights:
    semantic: float = 0.35
    keyword: float = 0.20
    importance: float = 0.15
    confidence: float = 0.10
    recency: float = 0.10
    reinforcement: float = 0.10

    def normalized(self) -> RankerWeights:
        total = (self.semantic + self.keyword + self.importance
                 + self.confidence + self.recency + self.reinforcement)
        if total <= 0:  # misconfiguration → fall back to equal weighting
            return RankerWeights(*([1 / 6] * 6))
        return RankerWeights(
            self.semantic / total, self.keyword / total, self.importance / total,
            self.confidence / total, self.recency / total, self.reinforcement / total,
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> RankerWeights:
        s = settings or get_settings()
        return cls(
            semantic=s.ranker_weight_semantic, keyword=s.ranker_weight_keyword,
            importance=s.ranker_weight_importance, confidence=s.ranker_weight_confidence,
            recency=s.ranker_weight_recency, reinforcement=s.ranker_weight_reinforcement,
        ).normalized()


def _recency(created_at: datetime) -> float:
    age_days = (datetime.now(UTC) - created_at).total_seconds() / 86400.0
    return 0.5 ** (age_days / _RECENCY_HALFLIFE_DAYS)


@dataclass
class RankedMemory:
    candidate: ScoredCandidate
    score: float
    score_breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def memory(self):
        return self.candidate.memory


class Ranker:
    def __init__(
        self, weights: RankerWeights | None = None, *, score_floor: float | None = None
    ) -> None:
        self._w = weights or RankerWeights.from_settings()
        self._floor = score_floor if score_floor is not None else get_settings().ranker_score_floor

    def rank(self, candidates: list[ScoredCandidate], top_k: int = 5) -> list[RankedMemory]:
        w = self._w
        ranked: list[RankedMemory] = []
        for c in candidates:
            m = c.memory
            # Raw, normalized [0,1] component signals (explainability, invariant #8).
            breakdown = {
                "vector_similarity": round(c.semantic, 4),
                "keyword_score": round(c.keyword, 4),
                "importance_score": round(m.importance / 10.0, 4),
                "confidence": round(m.confidence, 4),
                "recency": round(_recency(m.created_at), 4),
                "reinforcement": round(min(m.reinforcement_count / 5.0, 1.0), 4),
            }
            score = round(
                w.semantic * breakdown["vector_similarity"]
                + w.keyword * breakdown["keyword_score"]
                + w.importance * breakdown["importance_score"]
                + w.confidence * breakdown["confidence"]
                + w.recency * breakdown["recency"]
                + w.reinforcement * breakdown["reinforcement"],
                4,
            )
            ranked.append(RankedMemory(candidate=c, score=score, score_breakdown=breakdown))
        ranked.sort(key=lambda r: r.score, reverse=True)
        # Keep only candidates with at least a weak signal.
        return [r for r in ranked if r.score > self._floor][:top_k]
