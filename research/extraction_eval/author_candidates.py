"""Authoring utility — emit a templated DRAFT candidate set toward the locked 150.

These are **drafts** (`authoring_status="draft"`, `review_status="unreviewed"`): a
deterministic authoring *workspace* / scheduling fixture, **not** gold and **not**
independently reviewed. Humans must replace/refine and approve every case before it is
locked (`lock_dataset` refuses non-approved cases). The generator only guarantees valid
structure and the locked category composition so the runner/scheduler can be validated
offline (e.g. the 2,400-run final dry-run).

    python -m research.extraction_eval.author_candidates \
      --out research/extraction_eval/datasets/draft/candidate_cases.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .dataset import LOCKED_COMPOSITION


def _case(cid: str, category: str, i: int) -> dict:
    base = {
        "case_id": cid, "category": category, "difficulty": "medium",
        "annotator_notes": "DRAFT template — replace with a human-authored case before approval",
        "authoring_status": "draft", "review_status": "unreviewed", "dataset_version": "v1-draft",
    }
    if category in ("no_persistent_memory", "low_utility_ambiguous"):
        return {**base, "conversation": [{"turn_id": "t1", "role": "user",
                "content": f"[draft {cid}] just a passing remark, number {i}."}],
                "target_turn_id": "t1", "gold": {"expected_noop": True, "atoms": [],
                "reason": "draft template no-op"}}
    if category == "multi_memory":
        atoms = [
            {"atom_id": f"{cid}_a", "memory_text": f"User draft fact A {i}.", "accepted_phrasings": [],
             "memory_type": "semantic", "subject": "user", "operation": "create", "should_store": True,
             "policy_disposition": "save", "supersedes": None, "source_turn_ids": ["t1"]},
            {"atom_id": f"{cid}_b", "memory_text": f"User draft fact B {i}.", "accepted_phrasings": [],
             "memory_type": "semantic", "subject": "user", "operation": "create", "should_store": True,
             "policy_disposition": "save", "supersedes": None, "source_turn_ids": ["t1"]},
        ]
        return {**base, "conversation": [{"turn_id": "t1", "role": "user",
                "content": f"[draft {cid}] fact A {i} and fact B {i}."}],
                "target_turn_id": "t1", "gold": {"expected_noop": False, "atoms": atoms}}
    if category == "update_contradiction":
        return {**base, "conversation": [
                {"turn_id": "t1", "role": "user", "content": f"[draft {cid}] value is X{i}."},
                {"turn_id": "t2", "role": "user", "content": f"[draft {cid}] actually value is Y{i} now."}],
                "target_turn_id": "t2", "gold": {"expected_noop": False, "atoms": [
                    {"atom_id": f"{cid}_a", "memory_text": f"User value is Y{i}.", "accepted_phrasings": [],
                     "memory_type": "semantic", "subject": "user", "operation": "update", "should_store": True,
                     "policy_disposition": "update_existing", "supersedes": f"User value is X{i}.",
                     "source_turn_ids": ["t2"]}]}}
    if category == "sensitive_policy_boundary":
        return {**base, "difficulty": "hard", "conversation": [{"turn_id": "t1", "role": "user",
                "content": f"[draft {cid}] my secret token is TOKEN-{i:04d}-EXAMPLE"}],
                "target_turn_id": "t1", "gold": {"expected_noop": False, "atoms": [
                    {"atom_id": f"{cid}_a", "memory_text": "User shared a secret token.",
                     "accepted_phrasings": [], "memory_type": "system", "subject": "user",
                     "operation": "create", "should_store": False, "policy_disposition": "block",
                     "supersedes": None, "source_turn_ids": ["t1"]}]}}
    # single_memory + temporal_negation → one atom (temporal uses a negation).
    text = f"User does not like item {i}." if category == "temporal_negation" else f"User prefers option {i}."
    mtype = "constraint" if category == "temporal_negation" else "preference"
    return {**base, "conversation": [{"turn_id": "t1", "role": "user",
            "content": f"[draft {cid}] {text}"}], "target_turn_id": "t1",
            "gold": {"expected_noop": False, "atoms": [
                {"atom_id": f"{cid}_a", "memory_text": text, "accepted_phrasings": [],
                 "memory_type": mtype, "subject": "user", "operation": "create", "should_store": True,
                 "policy_disposition": "save", "supersedes": None, "source_turn_ids": ["t1"]}]}}


def generate() -> list[dict]:
    cases = []
    for category, n in LOCKED_COMPOSITION.items():
        for i in range(1, n + 1):
            cases.append(_case(f"{category}_c{i:03d}", category, i))
    return cases


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate a DRAFT candidate set (not gold)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    cases = generate()
    Path(args.out).write_text("\n".join(json.dumps(c) for c in cases) + "\n")
    print(f"wrote {len(cases)} DRAFT candidate cases → {args.out} (NOT gold; needs human authoring+approval)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
