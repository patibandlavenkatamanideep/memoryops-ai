"""Dataset locking tests (offline)."""

from __future__ import annotations

import json

import pytest

from research.extraction_eval.locking import LockError, append_errata, lock_dataset, verify_lock

_APPROVED = {
    "case_id": "c1", "category": "single_memory", "difficulty": "easy",
    "conversation": [{"turn_id": "t1", "role": "user", "content": "Remember I like tea."}],
    "target_turn_id": "t1",
    "gold": {"expected_noop": False, "atoms": [{
        "atom_id": "c1_a", "memory_text": "User likes tea.", "memory_type": "preference",
        "operation": "create", "policy_disposition": "save", "source_turn_ids": ["t1"]}]},
    "authoring_status": "approved", "review_status": "reviewed",
}


def _write(path, cases):
    path.write_text("\n".join(json.dumps(c) for c in cases) + "\n")


def test_lock_requires_approved(tmp_path):
    draft = {**_APPROVED, "authoring_status": "draft"}
    src = tmp_path / "draft.jsonl"
    _write(src, [draft])
    with pytest.raises(LockError):
        lock_dataset(src, tmp_path / "locked.jsonl", version="v1")


def test_lock_creates_snapshot_and_verifies(tmp_path):
    src = tmp_path / "approved.jsonl"
    _write(src, [_APPROVED])
    out = tmp_path / "locked.jsonl"
    manifest = lock_dataset(src, out, version="extraction_eval_v1")
    assert out.exists()
    assert out.with_suffix(".manifest.json").exists()
    assert out.with_suffix(".sha256").exists()
    assert manifest.case_count == 1 and manifest.atom_count == 1
    assert verify_lock(out) is True


def test_locked_cannot_be_silently_overwritten(tmp_path):
    src = tmp_path / "approved.jsonl"
    _write(src, [_APPROVED])
    out = tmp_path / "locked.jsonl"
    lock_dataset(src, out, version="v1")
    with pytest.raises(LockError):
        lock_dataset(src, out, version="v1")  # no overwrite


def test_tamper_breaks_hash(tmp_path):
    src = tmp_path / "approved.jsonl"
    _write(src, [_APPROVED])
    out = tmp_path / "locked.jsonl"
    lock_dataset(src, out, version="v1")
    out.write_text(out.read_text() + "\n{}  ")  # tamper
    assert verify_lock(out) is False


def test_errata_appends(tmp_path):
    errata = tmp_path / "errata.jsonl"
    append_errata(errata, dataset_version="v1", case_id="c1", issue="typo", resolution="v2 fixes it")
    lines = [json.loads(x) for x in errata.read_text().splitlines() if x.strip()]
    assert lines[0]["case_id"] == "c1" and lines[0]["dataset_version"] == "v1"
