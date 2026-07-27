"""Dataset locking — turn approved drafts into an immutable, hash-protected snapshot.

A locked dataset is the gold record for the study. Locking requires every case to be
human-``approved`` (never done automatically), writes a byte-stable JSONL snapshot plus
a manifest (counts, hashes, annotation-status summary) and a ``.sha256``, and refuses to
overwrite an existing lock — a change means a new version + an errata entry, preserving
the old snapshot (§7).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .dataset import atom_count, category_counts, dumps_jsonl, validate_cases
from .schema import Case


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class LockError(Exception):
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


@dataclass
class DatasetManifest:
    version: str
    created_at: str
    case_count: int
    atom_count: int
    sha256: str
    category_counts: dict[str, int]
    annotation_status: dict[str, int]
    review_status: dict[str, int]
    reviewers: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _require_approved(cases: list[Case]) -> list[str]:
    problems = []
    for c in cases:
        if c.authoring_status != "approved":
            problems.append(f"{c.case_id}: authoring_status={c.authoring_status!r} (must be 'approved' to lock)")
    return problems


def lock_dataset(
    input_path: str | Path,
    output_path: str | Path,
    *,
    version: str,
    expected_counts: dict[str, int] | None = None,
    force: bool = False,
) -> DatasetManifest:
    """Create an immutable locked snapshot from an approved draft.

    Raises ``LockError`` unless every case is approved and the dataset validates. Refuses
    to overwrite an existing locked file unless ``force`` (which the CLI never passes) —
    re-locking must mint a new version and record errata.
    """
    from .dataset import load_cases

    output_path = Path(output_path)
    if output_path.exists() and not force:
        raise LockError(
            f"{output_path} already exists — locked datasets are immutable; "
            "create a new version and record an errata entry instead of overwriting"
        )

    cases = load_cases(input_path)
    problems = validate_cases(cases, expected_counts=expected_counts) + _require_approved(cases)
    if problems:
        raise LockError("cannot lock:\n  - " + "\n  - ".join(problems))

    snapshot = dumps_jsonl(cases)
    digest = sha256_text(snapshot)
    manifest = DatasetManifest(
        version=version,
        created_at=datetime.now(UTC).isoformat(),
        case_count=len(cases),
        atom_count=atom_count(cases),
        sha256=digest,
        category_counts=category_counts(cases),
        annotation_status=dict(Counter(c.authoring_status for c in cases)),
        review_status=dict(Counter(c.review_status for c in cases)),
        reviewers=sorted({r for c in cases for r in _reviewers(c)}),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(snapshot)
    output_path.with_suffix(".manifest.json").write_text(json.dumps(manifest.to_dict(), indent=2))
    output_path.with_suffix(".sha256").write_text(digest + "\n")
    return manifest


def _reviewers(case: Case) -> list[str]:
    # Reviewer identities may be recorded in annotator_notes as "reviewer:<name>".
    return [tok.split(":", 1)[1] for tok in case.annotator_notes.split() if tok.startswith("reviewer:")]


def verify_lock(locked_path: str | Path) -> bool:
    """Recompute the snapshot hash and compare to the committed ``.sha256``."""
    locked_path = Path(locked_path)
    recorded = locked_path.with_suffix(".sha256").read_text().strip()
    actual = sha256_text(locked_path.read_text())
    return recorded == actual


def append_errata(errata_path: str | Path, *, dataset_version: str, case_id: str, issue: str, resolution: str) -> None:
    """Append an errata entry (JSONL). Locked data is never edited in place; errata +
    a new version are how post-lock issues are handled."""
    entry = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "dataset_version": dataset_version,
        "case_id": case_id,
        "issue": issue,
        "resolution": resolution,
    }
    p = Path(errata_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
