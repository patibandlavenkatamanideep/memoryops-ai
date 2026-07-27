"""Dataset loading + validation for extraction cases.

Cases are JSONL of the `schema.Case` model. Validation is strict: pydantic enforces
enums, no-op-has-no-atoms, and source-turn references; this module adds duplicate-id
and category-count checks. Model-generated cases are **drafts** until a human approves
them (see `locking.py`); nothing here marks a case gold.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from .schema import CATEGORIES, Case


def load_cases(path: str | Path) -> list[Case]:
    cases: list[Case] = []
    for i, line in enumerate(Path(path).read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            cases.append(Case.model_validate_json(line))
        except ValidationError as exc:
            raise ValueError(f"{path}:{i}: invalid case: {exc}") from exc
    return cases


def validate_cases(cases: list[Case], *, expected_counts: dict[str, int] | None = None) -> list[str]:
    """Return a list of human-readable problems (empty = valid). Never raises."""
    problems: list[str] = []
    ids = [c.case_id for c in cases]
    dups = [cid for cid, n in Counter(ids).items() if n > 1]
    if dups:
        problems.append(f"duplicate case_id(s): {sorted(dups)}")

    cat_counts = Counter(c.category for c in cases)
    for cat in cat_counts:
        if cat not in CATEGORIES:
            problems.append(f"unknown category {cat!r}")

    if expected_counts is not None:
        for cat, want in expected_counts.items():
            got = cat_counts.get(cat, 0)
            if got != want:
                problems.append(f"category {cat!r}: expected {want} cases, found {got}")
        total_want = sum(expected_counts.values())
        if len(cases) != total_want:
            problems.append(f"total: expected {total_want} cases, found {len(cases)}")

    for c in cases:
        # pydantic already blocks noop+atoms, but assert defensively for clear messages.
        if c.gold.expected_noop and c.gold.atoms:
            problems.append(f"{c.case_id}: expected_noop but has atoms")
        if not c.gold.expected_noop and not c.gold.atoms:
            problems.append(f"{c.case_id}: not no-op but has no atoms")
        atom_ids = [a.atom_id for a in c.gold.atoms]
        adup = [a for a, n in Counter(atom_ids).items() if n > 1]
        if adup:
            problems.append(f"{c.case_id}: duplicate atom_id(s) {adup}")
    return problems


# Locked-set composition (§6). Development set uses the same categories proportionally.
LOCKED_COMPOSITION = {
    "no_persistent_memory": 25,
    "single_memory": 30,
    "multi_memory": 35,
    "update_contradiction": 20,
    "temporal_negation": 15,
    "low_utility_ambiguous": 10,
    "sensitive_policy_boundary": 15,
}
DEVELOPMENT_COMPOSITION = {
    "no_persistent_memory": 5,
    "single_memory": 6,
    "multi_memory": 7,
    "update_contradiction": 4,
    "temporal_negation": 3,
    "low_utility_ambiguous": 2,
    "sensitive_policy_boundary": 3,
}
PILOT_COMPOSITION = {
    "no_persistent_memory": 3,
    "single_memory": 3,
    "multi_memory": 3,
    "update_contradiction": 2,
    "temporal_negation": 2,
    "sensitive_policy_boundary": 2,
}


def category_counts(cases: list[Case]) -> dict[str, int]:
    return dict(Counter(c.category for c in cases))


def atom_count(cases: list[Case]) -> int:
    return sum(len(c.gold.atoms) for c in cases)


def dumps_jsonl(cases: list[Case]) -> str:
    return "\n".join(c.model_dump_json() for c in cases) + "\n"
