"""Dataset validation tests (offline)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from research.extraction_eval.dataset import (
    DEVELOPMENT_COMPOSITION,
    load_cases,
    validate_cases,
)
from research.extraction_eval.schema import Case

_MINIMAL = {
    "case_id": "c1", "category": "single_memory", "difficulty": "easy",
    "conversation": [{"turn_id": "t1", "role": "user", "content": "Remember I like tea."}],
    "target_turn_id": "t1",
    "gold": {"expected_noop": False, "atoms": [{
        "atom_id": "c1_a", "memory_text": "User likes tea.", "memory_type": "preference",
        "operation": "create", "policy_disposition": "save", "source_turn_ids": ["t1"]}]},
}


def _case(**over):
    data = {**_MINIMAL, **over}
    return Case.model_validate(data)


def test_valid_case_loads():
    assert _case().case_id == "c1"


def test_missing_field_rejected():
    bad = {k: v for k, v in _MINIMAL.items() if k != "target_turn_id"}
    with pytest.raises(ValidationError):
        Case.model_validate(bad)


def test_invalid_enum_rejected():
    with pytest.raises(ValidationError):
        _case(category="bogus_category")


def test_invalid_source_turn_reference_rejected():
    bad = {**_MINIMAL, "gold": {"expected_noop": False, "atoms": [{
        "atom_id": "c1_a", "memory_text": "x", "memory_type": "semantic",
        "operation": "create", "policy_disposition": "save", "source_turn_ids": ["tNOPE"]}]}}
    with pytest.raises(ValidationError):
        Case.model_validate(bad)


def test_noop_cannot_have_atoms():
    with pytest.raises(ValidationError):
        Case.model_validate({**_MINIMAL, "gold": {"expected_noop": True, "atoms": _MINIMAL["gold"]["atoms"]}})


def test_duplicate_case_ids_reported():
    cases = [_case(), _case()]  # both c1
    problems = validate_cases(cases)
    assert any("duplicate" in p for p in problems)


def test_category_counts_validated():
    cases = [_case()]
    problems = validate_cases(cases, expected_counts=DEVELOPMENT_COMPOSITION)
    assert any("expected" in p for p in problems)  # 1 != 30


def test_committed_draft_dataset_is_valid():
    import pathlib

    ds = pathlib.Path(__file__).resolve().parents[1] / "datasets" / "development" / "cases.jsonl"
    problems = validate_cases(load_cases(ds))
    assert problems == [], problems
