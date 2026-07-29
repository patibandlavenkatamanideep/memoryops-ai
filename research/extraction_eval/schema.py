"""Provider-neutral structured output + gold schema for the extraction study.

Every provider (stub, Gemini, OpenAI, Anthropic) must return the same logical schema
so results are comparable. Enums reuse MemoryOps' canonical vocabulary where it exists
(see `MEMORY_TYPES` mirrored from `app.schemas.memory.MemoryType`, and
`POLICY_TO_CANONICAL` mapping `policy_disposition` onto the canonical `Decision`); a
contract test asserts they stay in sync so we never fork terminology.

Extraction (did the model pull the right atoms?) and storage disposition (should this
atom be saved / blocked / …) are modelled as **separate** fields and scored separately:
a sensitive atom correctly marked ``block`` is an extraction success, not a failure.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

# Mirror of app.schemas.memory.MemoryType (canonical). Kept as literals so the schema
# imports with no app dependency; `tests/test_schema_contract.py` asserts equality.
MEMORY_TYPES = (
    "episodic",
    "semantic",
    "procedural",
    "project",
    "knowledge",
    "system",
    "constraint",
    "preference",
    "workflow",
)


class Operation(str, Enum):
    """Lifecycle operation the extraction proposes for an atom (research vocabulary,
    distinct from storage disposition)."""

    create = "create"
    update = "update"
    merge = "merge"
    delete = "delete"
    none = "none"


class PolicyDisposition(str, Enum):
    """Predicted storage disposition. Values map 1:1 onto the canonical `Decision`
    enum (see `POLICY_TO_CANONICAL`); ``none`` is research-only for no-op turns."""

    save = "save"
    block = "block"
    pending_approval = "pending_approval"
    drop_low_utility = "drop_low_utility"
    update_existing = "update_existing"
    merge = "merge"
    none = "none"


# policy_disposition -> canonical app.schemas.memory.Decision member name.
POLICY_TO_CANONICAL = {
    PolicyDisposition.save: "SAVE",
    PolicyDisposition.block: "BLOCK",
    PolicyDisposition.pending_approval: "PENDING_APPROVAL",
    PolicyDisposition.drop_low_utility: "DROP_LOW_UTILITY",
    PolicyDisposition.update_existing: "UPDATE_EXISTING",
    PolicyDisposition.merge: "MERGE_WITH_EXISTING",
    # `none` has no canonical Decision — it denotes "no storage action" (no-op).
}


class MemoryAtom(BaseModel):
    """One atomic memory a model claims to extract from the target turn."""

    model_config = {"extra": "forbid"}

    memory_text: str = Field(min_length=1)
    memory_type: str
    subject: str = "user"
    operation: Operation = Operation.create
    should_store: bool = True
    policy_disposition: PolicyDisposition = PolicyDisposition.save
    supersedes: str | None = None
    source_turn_ids: list[str] = Field(default_factory=list)

    @field_validator("memory_type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in MEMORY_TYPES:
            raise ValueError(f"unknown memory_type {v!r}; expected one of {MEMORY_TYPES}")
        return v


class ExtractionOutput(BaseModel):
    """The provider-neutral structured output every adapter normalises to."""

    model_config = {"extra": "forbid"}

    memories: list[MemoryAtom] = Field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        return len(self.memories) == 0


# ── gold (dataset) schema ────────────────────────────────────────────────────
class GoldAtom(BaseModel):
    model_config = {"extra": "forbid"}

    atom_id: str
    memory_text: str = Field(min_length=1)
    accepted_phrasings: list[str] = Field(default_factory=list)
    memory_type: str
    subject: str = "user"
    operation: Operation = Operation.create
    should_store: bool = True
    policy_disposition: PolicyDisposition = PolicyDisposition.save
    supersedes: str | None = None
    source_turn_ids: list[str] = Field(default_factory=list)

    @field_validator("memory_type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in MEMORY_TYPES:
            raise ValueError(f"unknown memory_type {v!r}")
        return v


class Gold(BaseModel):
    model_config = {"extra": "forbid"}

    expected_noop: bool
    atoms: list[GoldAtom] = Field(default_factory=list)
    reason: str = ""

    @field_validator("atoms")
    @classmethod
    def _noop_has_no_atoms(cls, v, info):
        # Enforced here AND in dataset validation: a no-op case cannot carry atoms.
        if info.data.get("expected_noop") and v:
            raise ValueError("expected_noop=true but atoms are present")
        return v


class Turn(BaseModel):
    model_config = {"extra": "forbid"}

    turn_id: str
    role: str = "user"
    content: str = Field(min_length=1)


CATEGORIES = (
    "no_persistent_memory",
    "single_memory",
    "multi_memory",
    "update_contradiction",
    "temporal_negation",
    "low_utility_ambiguous",
    "sensitive_policy_boundary",
)

DIFFICULTIES = ("easy", "medium", "hard")
AUTHORING_STATUS = ("draft", "authored", "approved")
REVIEW_STATUS = ("unreviewed", "reviewed", "adjudicated")


class Case(BaseModel):
    model_config = {"extra": "forbid"}

    case_id: str
    category: str
    difficulty: str = "medium"
    conversation: list[Turn]
    target_turn_id: str
    gold: Gold
    annotator_notes: str = ""
    authoring_status: str = "draft"
    review_status: str = "unreviewed"
    dataset_version: str = "v1-draft"

    @field_validator("category")
    @classmethod
    def _known_category(cls, v: str) -> str:
        if v not in CATEGORIES:
            raise ValueError(f"unknown category {v!r}; expected one of {CATEGORIES}")
        return v

    @field_validator("difficulty")
    @classmethod
    def _known_difficulty(cls, v: str) -> str:
        if v not in DIFFICULTIES:
            raise ValueError(f"unknown difficulty {v!r}")
        return v

    def model_post_init(self, _ctx) -> None:
        turn_ids = {t.turn_id for t in self.conversation}
        if self.target_turn_id not in turn_ids:
            raise ValueError(f"target_turn_id {self.target_turn_id!r} not in conversation")
        for atom in self.gold.atoms:
            for stid in atom.source_turn_ids:
                if stid not in turn_ids:
                    raise ValueError(f"atom {atom.atom_id}: source turn {stid!r} not in conversation")
