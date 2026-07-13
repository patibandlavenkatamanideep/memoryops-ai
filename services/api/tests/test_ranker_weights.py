"""Ranker weights are configurable + normalized (P3.2)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.db.entities import StoredMemory
from app.schemas.memory import MemoryType, Sensitivity, Source, Status
from app.services.ranker import Ranker, RankerWeights
from app.services.retriever import ScoredCandidate


def _candidate(semantic: float, keyword: float, importance: int = 5) -> ScoredCandidate:
    m = StoredMemory(
        tenant_id="t", user_id="u", memory_type=MemoryType.semantic, content="x",
        importance=importance, confidence=0.7, sensitivity=Sensitivity.low,
        status=Status.active, source=Source(kind="test"), created_at=datetime.now(UTC),
    )
    return ScoredCandidate(memory=m, semantic=semantic, keyword=keyword)


def test_default_weights_sum_to_one_and_are_unchanged():
    w = RankerWeights()
    n = w.normalized()
    assert abs(sum([n.semantic, n.keyword, n.importance, n.confidence, n.recency,
                    n.reinforcement]) - 1.0) < 1e-9
    assert (n.semantic, n.keyword) == (0.35, 0.20)  # already summed to 1 → no change


def test_weights_are_normalized_when_they_do_not_sum_to_one():
    w = RankerWeights(semantic=7, keyword=3, importance=0, confidence=0,
                      recency=0, reinforcement=0).normalized()
    assert abs(w.semantic - 0.7) < 1e-9 and abs(w.keyword - 0.3) < 1e-9


def test_zero_weights_fall_back_to_equal():
    w = RankerWeights(0, 0, 0, 0, 0, 0).normalized()
    assert abs(w.semantic - 1 / 6) < 1e-9


def test_custom_weights_change_ranking_order():
    cands = [_candidate(semantic=0.9, keyword=0.0), _candidate(semantic=0.0, keyword=0.9)]
    semantic_ranker = Ranker(RankerWeights(semantic=1, keyword=0, importance=0,
                                           confidence=0, recency=0, reinforcement=0))
    keyword_ranker = Ranker(RankerWeights(semantic=0, keyword=1, importance=0,
                                          confidence=0, recency=0, reinforcement=0))
    assert semantic_ranker.rank(cands)[0].candidate.semantic == 0.9
    assert keyword_ranker.rank(cands)[0].candidate.keyword == 0.9


def test_ranker_reads_weights_from_settings(monkeypatch):
    monkeypatch.setenv("MEMORYOPS_RANK_W_KEYWORD", "1.0")
    monkeypatch.setenv("MEMORYOPS_RANK_W_SEMANTIC", "0.0")
    monkeypatch.setenv("MEMORYOPS_RANK_W_IMPORTANCE", "0.0")
    monkeypatch.setenv("MEMORYOPS_RANK_W_CONFIDENCE", "0.0")
    monkeypatch.setenv("MEMORYOPS_RANK_W_RECENCY", "0.0")
    monkeypatch.setenv("MEMORYOPS_RANK_W_REINFORCEMENT", "0.0")
    from app.core.config import get_settings

    get_settings.cache_clear()
    ranker = Ranker()
    get_settings.cache_clear()
    cands = [_candidate(semantic=0.9, keyword=0.1), _candidate(semantic=0.1, keyword=0.9)]
    assert ranker.rank(cands)[0].candidate.keyword == 0.9
