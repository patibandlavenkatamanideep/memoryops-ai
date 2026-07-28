"""Deterministic atom matching (the primary scorer — no LLM judge, §15).

A predicted atom matches a gold atom by, in order: normalised exact text, an accepted
phrasing, or a preregistered lexical-similarity rule (token Jaccard ≥ threshold).
Predicted↔gold atoms are paired by greedy maximum-weight one-to-one matching (small
atom counts; deterministic tie-break on ids). Thresholds live in the experiment config
and are frozen before locked results; borderline pairs are surfaced for human
adjudication rather than silently accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "to", "of", "is", "are", "and", "i", "my", "user", "user's"}


def normalize(text: str) -> str:
    return _WS.sub(" ", _PUNCT.sub(" ", (text or "").lower())).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP}


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def pair_score(pred_text: str, gold_text: str, accepted: list[str], *, threshold: float) -> float:
    """1.0 for exact/alias match; else the Jaccard score iff ≥ threshold, else 0.0."""
    npred = normalize(pred_text)
    if npred == normalize(gold_text):
        return 1.0
    if any(npred == normalize(p) for p in accepted):
        return 1.0
    j = jaccard(pred_text, gold_text)
    for p in accepted:
        j = max(j, jaccard(pred_text, p))
    return j if j >= threshold else 0.0


@dataclass
class Match:
    pred_index: int
    gold_index: int
    score: float
    is_exact: bool


@dataclass
class MatchResult:
    matches: list[Match]
    unmatched_pred: list[int]  # false memories (FP)
    unmatched_gold: list[int]  # missed memories (FN)
    borderline: list[tuple[int, int, float]]  # near-threshold pairs for adjudication


def match_atoms(
    pred_texts_and_meta, gold_atoms, *, threshold: float, borderline_band: float = 0.05
) -> MatchResult:
    """Greedy max-weight one-to-one matching. ``pred_texts_and_meta`` is a list of
    predicted ``memory_text`` strings; ``gold_atoms`` is a list of gold atoms."""
    edges: list[tuple[float, bool, int, int]] = []
    for pi, ptext in enumerate(pred_texts_and_meta):
        for gi, gold in enumerate(gold_atoms):
            s = pair_score(ptext, gold.memory_text, gold.accepted_phrasings, threshold=threshold)
            exact = s == 1.0
            if s > 0:
                edges.append((s, exact, pi, gi))
    # Deterministic order: highest score first, then exactness, then indices.
    edges.sort(key=lambda e: (-e[0], not e[1], e[2], e[3]))

    used_pred: set[int] = set()
    used_gold: set[int] = set()
    matches: list[Match] = []
    borderline: list[tuple[int, int, float]] = []
    for score, exact, pi, gi in edges:
        if pi in used_pred or gi in used_gold:
            continue
        matches.append(Match(pi, gi, score, exact))
        used_pred.add(pi)
        used_gold.add(gi)
        if not exact and score < threshold + borderline_band:
            borderline.append((pi, gi, score))

    unmatched_pred = [i for i in range(len(pred_texts_and_meta)) if i not in used_pred]
    unmatched_gold = [i for i in range(len(gold_atoms)) if i not in used_gold]
    return MatchResult(matches, unmatched_pred, unmatched_gold, borderline)
