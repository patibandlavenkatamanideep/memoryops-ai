"""Output Gate — post-generation disclosure control (v1.9, ADR-023).

The Recall/Admission gates decide what memory enters the prompt. The **Output Gate**
is the mirror on the way out: it inspects the *generated answer* and catches content
that would disclose memory those gates deliberately withheld — a real LLM that ignores
instructions and echoes withheld context, prompt-injection that coaxes it out, or a
model that infers and restates blocked material.

Deterministic + no-throw (invariant #4): it flags a disclosure when the answer shares a
distinctive contiguous phrase with a *protected* (blocked) memory, then either redacts
those spans or refuses. It never fabricates content and never blocks on error — on any
failure it returns the original answer unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_WORD = re.compile(r"[a-z0-9]+")
_MIN_PHRASE_WORDS = 4  # a shared run this long is a disclosure, not a coincidence
_REDACTION = "[redacted]"


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _ngrams(words: list[str], n: int) -> set[tuple[str, ...]]:
    if len(words) < n:
        return set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


@dataclass
class OutputReview:
    answer: str
    action: str = "allow"  # allow | redacted | refused
    disclosures: int = 0
    escalated: bool = False
    protected_ids: list[str] = field(default_factory=list)


class OutputGate:
    """Catch memory-derived disclosure in the final answer.

    `mode` = "redact" (default) replaces the offending spans; "refuse" returns a safe
    refusal message when any disclosure is found.
    """

    _REFUSAL = (
        "I can't share that — it would disclose information that isn't permitted in "
        "this context."
    )

    def __init__(self, *, mode: str = "redact", min_phrase_words: int = _MIN_PHRASE_WORDS) -> None:
        self._mode = mode
        self._n = max(2, min_phrase_words)

    def review(self, answer: str, *, protected: list) -> OutputReview:
        """`protected` = memories that must NOT be disclosed (the blocked records)."""
        if not answer or not protected:
            return OutputReview(answer=answer)
        try:
            return self._review(answer, protected)
        except Exception:  # noqa: BLE001 - never let the gate break a response
            return OutputReview(answer=answer)

    def _review(self, answer: str, protected: list) -> OutputReview:
        # Token spans over the original answer (positions are identical on the
        # lowercased copy since casefolding preserves length here).
        tokens = list(_WORD.finditer(answer.lower()))
        words = [t.group() for t in tokens]
        answer_ngrams = _ngrams(words, self._n)

        # Union of all protected phrases, plus which memory each came from.
        hit_ids: list[str] = []
        protected_phrases: set[tuple[str, ...]] = set()
        for rec in protected:
            memory = getattr(rec, "memory", rec)
            phrases = _ngrams(_words(getattr(memory, "content", "") or ""), self._n)
            if phrases & answer_ngrams:
                hit_ids.append(getattr(memory, "id", "?"))
                protected_phrases |= phrases
        if not hit_ids:
            return OutputReview(answer=answer)

        # Mark every word index covered by any shared phrase, then redact each
        # maximal covered run in one pass — order-independent, no leftover fragments.
        covered: set[int] = set()
        for i in range(len(words) - self._n + 1):
            if tuple(words[i : i + self._n]) in protected_phrases:
                covered.update(range(i, i + self._n))
        redacted = self._redact_runs(answer, tokens, covered)
        if self._mode == "refuse":
            return OutputReview(
                answer=self._REFUSAL, action="refused",
                disclosures=len(hit_ids), escalated=True, protected_ids=hit_ids,
            )
        return OutputReview(
            answer=redacted, action="redacted",
            disclosures=len(hit_ids), escalated=True, protected_ids=hit_ids,
        )

    @staticmethod
    def _redact_runs(answer: str, tokens: list, covered: set[int]) -> str:
        """Replace each maximal run of covered word-spans with a single [redacted]."""
        out: list[str] = []
        cursor = 0
        i = 0
        n = len(tokens)
        while i < n:
            if i in covered:
                j = i
                while j + 1 < n and (j + 1) in covered:
                    j += 1
                out.append(answer[cursor : tokens[i].start()])
                out.append(_REDACTION)
                cursor = tokens[j].end()
                i = j + 1
            else:
                i += 1
        out.append(answer[cursor:])
        return "".join(out)
