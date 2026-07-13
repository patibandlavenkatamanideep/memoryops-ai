"""Deterministic heuristics — the universal fallback for the LLM layer (v0.4).

When no provider is configured, a provider fails, times out, or returns invalid
JSON, the structured-intelligence layer degrades to these pure-Python heuristics
(invariant #4). They are deterministic and require no API key, which keeps the
StubProvider and the whole test suite offline-safe.

The extraction heuristic is the canonical behavior the golden evals depend on; it
lived in ``services/extractor.py`` before v0.4 and now has one home so both the
extractor and the StubProvider share it without duplication.
"""

from __future__ import annotations

import re

from ..schemas.memory import MemoryType, Sensitivity
from .schemas import (
    ConflictDetectionResult,
    ConflictItem,
    ExtractedMemory,
    MemoryEvaluationResult,
)

# Cues that a turn contains something worth remembering.
_REMEMBER_CUES = re.compile(
    r"\b(remember|note that|keep in mind|for future reference|don'?t forget|make a note|"
    r"save (this|that|it|for later)|store (this|that|it))\b",
    re.IGNORECASE,
)
_PREFERENCE_CUES = re.compile(
    r"\b(i (prefer|like|love|hate|dislike|always|never|usually|want)|my (preference|style))\b",
    re.IGNORECASE,
)
_CONSTRAINT_CUES = re.compile(
    r"\b(never|do not|don'?t|always|must not|must|avoid)\b", re.IGNORECASE
)
_PROJECT_CUES = re.compile(
    r"\b(i'?m (building|working on)|my project|we'?re building)\b", re.IGNORECASE
)


def _classify(text: str) -> MemoryType:
    if _PROJECT_CUES.search(text):
        return MemoryType.project
    if _PREFERENCE_CUES.search(text):
        # Procedural = how the user wants things done; preference = like/dislike.
        if re.search(r"\b(explain|answer|respond|format|style|tone)\b", text, re.IGNORECASE):
            return MemoryType.procedural
        return MemoryType.preference
    if _CONSTRAINT_CUES.search(text):
        return MemoryType.constraint
    return MemoryType.semantic


def _strip_remember_prefix(text: str) -> str:
    cleaned = re.sub(
        r"^\s*(please\s+)?(remember( that)?|note that|keep in mind( that)?|"
        r"for future reference,?|make a note( that)?|save (this|that|it)( for later)?:?|"
        r"store (this|that|it):?)\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return cleaned.strip().rstrip(".") + "." if cleaned.strip() else text.strip()


# Split a message into independent memory-bearing clauses. We break on sentence
# terminators, and on a comma / "and" that introduces a *new first-person clause*
# ("…, I'm allergic…", "…and my anniversary…") — but NOT on a comma that merely
# continues a thought ("window seats, especially long-haul"), so single statements
# stay whole.
_CLAUSE_SPLIT = re.compile(
    r"[.!?;]\s+"
    r"|\s*,\s+(?=(?:and\s+|but\s+)?(?:i\b|i'|my\b|we\b|we'|our\b))"
    r"|\s+and\s+(?=(?:i\b|i'|my\b|we\b|we'|our\b))",
    re.IGNORECASE,
)


_LEADING_CONJ = re.compile(r"^(and|but|also)\s+", re.IGNORECASE)


def _split_clauses(text: str) -> list[str]:
    parts = (_LEADING_CONJ.sub("", c.strip()) for c in _CLAUSE_SPLIT.split(text) if c)
    return [c for c in parts if c.strip()]


def _as_memory(clause: str, *, explicit: bool) -> ExtractedMemory:
    return ExtractedMemory(
        content=clause.rstrip(".") + ".",
        type=_classify(clause),
        # Explicit "remember" → higher importance/confidence than an inferred one.
        importance=8 if explicit else 6,
        confidence=0.92 if explicit else 0.7,
        sensitivity=Sensitivity.low,
        rationale="heuristic: explicit cue" if explicit else "heuristic: inferred statement",
    )


def heuristic_extract(message: str, *, max_memories: int = 5) -> list[ExtractedMemory]:
    """Deterministic extraction: recognize explicit/implicit memory statements.

    Handles compound turns: an explicit "remember A, B and C" or a message with
    several first-person preference/project clauses yields multiple memories (up to
    ``max_memories``). A single statement still yields exactly one memory with the
    whole message as content, so the golden evals remain stable. Sensitivity is left
    ``low`` and the policy broker assigns the final value.
    """
    text = message.strip()
    if not text:
        return []

    explicit = bool(_REMEMBER_CUES.search(text))
    statement = bool(_PREFERENCE_CUES.search(text) or _PROJECT_CUES.search(text))
    if not (explicit or statement):
        # Pure questions / chit-chat don't produce memory candidates.
        return []

    body = _strip_remember_prefix(text) if explicit else text
    clauses = _split_clauses(body)

    if explicit:
        # The user asked to store the whole list — every non-trivial clause counts.
        candidates = [c for c in clauses if len(c) >= 3]
    else:
        # Inferred: only clauses that themselves state a preference/project.
        candidates = [
            c for c in clauses
            if len(c) >= 3 and (_PREFERENCE_CUES.search(c) or _PROJECT_CUES.search(c))
        ]

    # Single-memory turns keep the pre-v0.4 behavior exactly: one memory whose
    # content is the whole (prefix-stripped) message.
    if len(candidates) <= 1:
        content = _strip_remember_prefix(text) if explicit else text.rstrip(".") + "."
        return [_as_memory(content, explicit=explicit)]

    out: list[ExtractedMemory] = []
    seen: set[str] = set()
    for clause in candidates:
        mem = _as_memory(clause, explicit=explicit)
        if mem.content.lower() in seen:
            continue
        seen.add(mem.content.lower())
        out.append(mem)
        if len(out) >= max_memories:
            break
    return out


def heuristic_evaluate(memory: ExtractedMemory) -> MemoryEvaluationResult:
    """Deterministic advisory evaluation mirroring the extracted scores."""
    return MemoryEvaluationResult(
        suggested_importance=memory.importance,
        suggested_sensitivity=memory.sensitivity,
        is_worth_remembering=memory.importance >= 4,
        rationale="heuristic evaluation",
    )


_NEGATIONS = re.compile(r"\b(no longer|not|never|stop|don'?t|switched? to|instead of)\b", re.I)
_TOKEN = re.compile(r"[a-z0-9]+")


def _content_tokens(text: str) -> set[str]:
    stop = {"i", "a", "an", "the", "to", "of", "my", "is", "are", "that", "this", "it", "for"}
    return {t for t in _TOKEN.findall(text.lower()) if t not in stop and len(t) > 2}


def heuristic_conflicts(
    candidate_content: str, existing: list[tuple[str, str]]
) -> ConflictDetectionResult:
    """Minimal deterministic conflict detection.

    ``existing`` is a list of ``(memory_id, content)``. A conflict is flagged when
    a candidate shares meaningful subject tokens with an existing memory and one
    of the two contains a negation/switch cue the other does not — a cheap proxy
    for "the user changed their mind". This is advisory metadata only.
    """
    cand_tokens = _content_tokens(candidate_content)
    cand_neg = bool(_NEGATIONS.search(candidate_content))
    conflicts: list[ConflictItem] = []
    for mem_id, content in existing:
        overlap = cand_tokens & _content_tokens(content)
        if len(overlap) < 2:
            continue
        exist_neg = bool(_NEGATIONS.search(content))
        if cand_neg != exist_neg:
            conflicts.append(
                ConflictItem(
                    existing_memory_id=mem_id,
                    existing_content=content,
                    relation="contradicts",
                    explanation=(
                        "shared subject "
                        f"({', '.join(sorted(overlap))}) with opposing polarity"
                    ),
                )
            )
    return ConflictDetectionResult(has_conflict=bool(conflicts), conflicts=conflicts)
