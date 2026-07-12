"""Dependency-free BM25 keyword scoring for the retriever (P3.1).

The retriever previously scored keywords as raw query/candidate token-set overlap:
no stopword removal, no term weighting, so "the"/"what"/"my" counted the same as
"cardiologist". BM25 fixes both — rare, discriminative terms dominate and common
words are damped — computed over just the candidate set the vector search returns
(a few hundred rows), so no index infrastructure is needed. Implemented in pure
Python to match the codebase's dependency-free style (cf. metrics/tracing/JWT-less
paths); `rank_bm25` is a drop-in alternative if a dependency is ever preferred.

For large-corpus Postgres, `websearch_to_tsquery`/`ts_rank` is the upgrade path (see
docs/architecture.md).
"""

from __future__ import annotations

import math
import re
from collections import Counter

_WORD = re.compile(r"[a-z0-9]+")

# Small, high-frequency stopword set — enough to stop function words from dominating
# overlap without needing a full NLP dependency.
_STOP = frozenset(
    """a an the and or but if then else of to in on at by for with without from into
    over under again further is are was were be been being do does did doing have has
    had having i me my we our you your he she it they them this that these those what
    which who whom whose when where why how not no nor so than too very can will just
    about as up down out off am were""".split()
)


def _stem(word: str) -> str:
    """A tiny suffix stripper — collapses common morphological variants."""
    for suf in ("ing", "edly", "ed", "ly", "ies", "es", "s"):
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)]
    return word


def tokenize(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


class BM25:
    """BM25 Okapi over a fixed candidate corpus."""

    def __init__(self, corpus: list[list[str]], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.n = len(corpus)
        self.doc_len = [len(d) for d in corpus]
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0
        self.tf = [Counter(d) for d in corpus]
        df: Counter[str] = Counter()
        for doc in corpus:
            df.update(set(doc))
        # Non-negative BM25+ style idf so common terms never contribute a negative score.
        self.idf = {t: math.log(1 + (self.n - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out: list[float] = []
        for i in range(self.n):
            tf_i = self.tf[i]
            dl = self.doc_len[i]
            s = 0.0
            for term in query:
                f = tf_i.get(term, 0)
                if not f:
                    continue
                idf = self.idf.get(term, 0.0)
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1.0))
                s += idf * (f * (self.k1 + 1)) / denom
            out.append(s)
        return out


def bm25_scores(query: str, documents: list[str]) -> list[float]:
    """BM25 score per document, normalized to [0, 1] (0 when nothing matches)."""
    corpus = [tokenize(d) for d in documents]
    bm25 = BM25(corpus)
    raw = bm25.scores(tokenize(query))
    top = max(raw) if raw else 0.0
    if top <= 0:
        return [0.0] * len(documents)
    return [s / top for s in raw]
