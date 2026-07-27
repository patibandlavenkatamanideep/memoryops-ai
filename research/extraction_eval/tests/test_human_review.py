"""Human-review tooling tests (offline)."""

from __future__ import annotations

from research.extraction_eval.human_review import (
    cohen_kappa,
    compute_agreement,
    export_annotation_package,
    stratified_sample,
    validate_completeness,
)
from research.extraction_eval.schema import Case

_CASE = {
    "category": "single_memory", "difficulty": "easy",
    "conversation": [{"turn_id": "t1", "role": "user", "content": "Remember I like tea."}],
    "target_turn_id": "t1",
    "gold": {"expected_noop": False, "atoms": [{
        "atom_id": "a", "memory_text": "User likes tea.", "memory_type": "preference",
        "operation": "create", "policy_disposition": "save", "source_turn_ids": ["t1"]}]},
}


def _cases(n):
    cats = ["single_memory", "multi_memory", "no_persistent_memory"]
    out = []
    for i in range(n):
        cat = cats[i % len(cats)]
        gold = {"expected_noop": True, "atoms": []} if cat == "no_persistent_memory" else _CASE["gold"]
        out.append(Case.model_validate({**_CASE, "case_id": f"c{i}", "category": cat, "gold": gold}))
    return out


def test_cohen_kappa_perfect_and_chance():
    assert cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    assert cohen_kappa([1, 1, 1, 1], [1, 1, 1, 1]) == 1.0
    k = cohen_kappa([1, 0, 1, 0], [0, 1, 0, 1])
    assert k < 0  # perfect disagreement


def test_stratified_sample_size_and_determinism():
    cases = _cases(30)
    a = stratified_sample(cases, n=9, seed=1)
    b = stratified_sample(cases, n=9, seed=1)
    assert len(a) == 9 and [c.case_id for c in a] == [c.case_id for c in b]


def test_export_is_provider_blind_and_has_reviewer_fields():
    pkg = export_annotation_package(_cases(3))
    assert all("provider" not in rec for rec in pkg)
    assert all(rec["reviewer"]["expected_noop"] is None for rec in pkg)


def test_agreement_and_completeness():
    cases = _cases(4)
    pkg = export_annotation_package(cases)
    # reviewer agrees with gold on expected_noop for all.
    anns = {rec["case_id"]: {**rec, "reviewer": {"expected_noop": rec["gold"]["expected_noop"], "atoms": []}}
            for rec in pkg}
    assert validate_completeness(pkg, anns) == []
    agr = compute_agreement(pkg, anns)
    noop = next(a for a in agr if a.field == "expected_noop")
    assert noop.percent_agreement == 1.0 and noop.kappa == 1.0
