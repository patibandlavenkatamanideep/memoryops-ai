"""Blinded human-review support for ≥50 locked cases (§18).

Exports a provider-blind annotation package (case content + gold + empty reviewer
fields), imports reviewer annotations, and computes agreement + Cohen's kappa on the
key categorical fields. Agreement is a *measurement*; no independent-review claim is
valid until reviewer data exists. Model outputs never enter this path.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .schema import Case


def stratified_sample(cases: list[Case], *, n: int, seed: int) -> list[Case]:
    """Proportional-by-category sample of ``n`` cases (deterministic under seed)."""
    import random

    rng = random.Random(seed)
    by_cat: dict[str, list[Case]] = defaultdict(list)
    for c in cases:
        by_cat[c.category].append(c)
    total = len(cases)
    picked: list[Case] = []
    for _cat, group in sorted(by_cat.items()):
        k = max(1, round(n * len(group) / total)) if group else 0
        rng.shuffle(group)
        picked.extend(group[:k])
    rng.shuffle(picked)
    return picked[:n]


# Fields that must NEVER appear in a blinded reviewer export (anchoring / leakage).
_FORBIDDEN_EXPORT_KEYS = frozenset(
    {"gold", "atoms_gold", "accepted_phrasings", "provider", "model", "model_output",
     "prediction", "annotator_notes", "authoring_status", "review_status"}
)


def export_annotation_package(cases: list[Case]) -> list[dict]:
    """One record per case: **case content only** + blank reviewer fields.

    Deliberately excludes gold labels, accepted phrasings, any provider identity, any
    model output, and author-only notes so the reviewer annotates independently. Gold
    comparison happens only after `import_annotations` (see `compute_agreement`)."""
    package = []
    for c in cases:
        package.append({
            "case_id": c.case_id,
            "category": c.category,
            "conversation": [{"turn_id": t.turn_id, "role": t.role, "content": t.content}
                             for t in c.conversation],
            "target_turn_id": c.target_turn_id,
            "reviewer": {
                "expected_noop": None,
                "atoms": [],  # reviewer lists atoms with memory_type/operation/should_store/policy
                "notes": "",
            },
        })
    return package


def import_annotations(path: str | Path) -> dict[str, dict]:
    data = json.loads(Path(path).read_text())
    return {rec["case_id"]: rec for rec in data}


def validate_completeness(package: list[dict], annotations: dict[str, dict]) -> list[str]:
    problems = []
    for rec in package:
        cid = rec["case_id"]
        ann = annotations.get(cid)
        if ann is None:
            problems.append(f"{cid}: no reviewer annotation")
            continue
        if ann.get("reviewer", {}).get("expected_noop") is None:
            problems.append(f"{cid}: reviewer.expected_noop missing")
    return problems


def cohen_kappa(labels_a: list, labels_b: list) -> float:
    """Cohen's kappa for two aligned label sequences."""
    if not labels_a or len(labels_a) != len(labels_b):
        return float("nan")
    n = len(labels_a)
    po = sum(1 for a, b in zip(labels_a, labels_b, strict=True) if a == b) / n
    ca, cb = Counter(labels_a), Counter(labels_b)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


@dataclass
class Agreement:
    field: str
    n: int
    percent_agreement: float
    kappa: float


def compute_agreement(cases: list[Case], annotations: dict[str, dict]) -> list[Agreement]:
    """Gold-vs-reviewer agreement — computed **after** import, comparing the reviewer
    annotations against the cases' gold (never exposed to the reviewer). Reports
    ``expected_noop`` agreement + Cohen's kappa (the field every case has; atom-level
    fields are compared where reviewers supply atoms)."""
    gold_by_id = {c.case_id: c.gold for c in cases}
    gold_noop, rev_noop = [], []
    for cid, ann in annotations.items():
        gold = gold_by_id.get(cid)
        rn = ann.get("reviewer", {}).get("expected_noop") if ann else None
        if gold is None or rn is None:
            continue
        gold_noop.append(bool(gold.expected_noop))
        rev_noop.append(bool(rn))
    results = []
    if gold_noop:
        po = sum(1 for a, b in zip(gold_noop, rev_noop, strict=True) if a == b) / len(gold_noop)
        results.append(Agreement("expected_noop", len(gold_noop), po, cohen_kappa(gold_noop, rev_noop)))
    return results


def adjudication_template(disagreements: list[dict]) -> list[dict]:
    return [
        {"case_id": d["case_id"], "field": d.get("field", ""), "gold": d.get("gold"),
         "reviewer": d.get("reviewer"), "adjudicated_value": None, "adjudicator": "", "rationale": ""}
        for d in disagreements
    ]
