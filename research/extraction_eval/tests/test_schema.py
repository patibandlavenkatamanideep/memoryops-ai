"""Schema + canonical-vocabulary contract (offline)."""

from __future__ import annotations

import pytest

from research.extraction_eval.schema import (
    MEMORY_TYPES,
    POLICY_TO_CANONICAL,
    ExtractionOutput,
    MemoryAtom,
    PolicyDisposition,
)


def test_memory_types_match_canonical():
    from app.schemas.memory import MemoryType

    assert set(MEMORY_TYPES) == {m.value for m in MemoryType}


def test_policy_disposition_maps_to_real_decisions():
    from app.schemas.memory import Decision

    names = {d.name for d in Decision}
    for disp, canonical in POLICY_TO_CANONICAL.items():
        assert canonical in names, f"{disp} -> {canonical} not a Decision"
    # `none` is intentionally research-only (no canonical Decision).
    assert PolicyDisposition.none not in POLICY_TO_CANONICAL


def test_atom_rejects_unknown_type_and_extra_keys():
    with pytest.raises(Exception):
        MemoryAtom(memory_text="x", memory_type="not_a_type")
    with pytest.raises(Exception):
        MemoryAtom(memory_text="x", memory_type="semantic", bogus=1)


def test_extraction_output_noop():
    assert ExtractionOutput(memories=[]).is_noop
    assert not ExtractionOutput(memories=[MemoryAtom(memory_text="x", memory_type="semantic")]).is_noop
