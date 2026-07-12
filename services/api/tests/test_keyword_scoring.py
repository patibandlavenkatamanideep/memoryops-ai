"""BM25 keyword scoring (P3.1) — stopword-aware, term-weighted retrieval signal."""

from __future__ import annotations

from app.services.keyword_scoring import bm25_scores, tokenize


def test_tokenize_drops_stopwords_and_stems():
    toks = tokenize("I am seeing the cardiologists")
    assert "the" not in toks and "am" not in toks
    assert "cardiolog" in toks or "cardiologist" in toks  # stemmed variant


def test_bm25_prefers_rare_term_over_stopword_match():
    docs = [
        "what is the plan for my day",              # overlaps only on stopwords
        "my cardiologist appointment is on friday",  # the discriminative match
    ]
    scores = bm25_scores("what about my cardiologist", docs)
    assert scores[1] > scores[0]


def test_bm25_normalized_and_zero_when_no_match():
    docs = ["completely unrelated content here", "another unrelated line"]
    scores = bm25_scores("cardiologist appointment", docs)
    assert scores == [0.0, 0.0]

    docs2 = ["cardiologist appointment friday", "grocery list"]
    scores2 = bm25_scores("cardiologist", docs2)
    assert max(scores2) == 1.0 and min(scores2) >= 0.0


def test_bm25_stopword_only_query_is_not_dominant():
    docs = ["the a of to", "cardiologist"]
    # A query of only stopwords tokenizes to nothing → all zeros, no false matches.
    assert bm25_scores("the a of", docs) == [0.0, 0.0]
