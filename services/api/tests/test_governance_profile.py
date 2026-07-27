"""Governance profile switch — S0-U / Experiment-C ablation apparatus (paper Phase 2).

`governance_profile=full` (default) is the frozen, fully-governed behavior — the
entire existing suite is the equivalence proof that the default changes nothing.
`governance_profile=disabled` turns off policy-broker enforcement, the context gates,
transactional evidence, and tombstone propagation: the mechanism-matched ungoverned
twin. Individual `MEMORYOPS_ABLATE_*` flags disable exactly one control for Experiment
C without flipping the whole profile.
"""

from __future__ import annotations

import pytest

from app.core import config
from app.db.memory_repo import InMemoryRepository
from app.schemas.memory import CandidateMemory, Decision
from app.services.policy_broker import PolicyBroker
from app.workers.decay import DecayWorker
from app.workers.lifecycle import WorkerContext
from app.workers.schemas import MEMORY_DECAY_APPLIED, WorkerRunStatus

from ._worker_helpers import NOW, seed_memory
from .test_worker_atomicity import _CrashOnAction


@pytest.fixture
def load_settings(monkeypatch):
    """Load Settings under a given env, isolating the lru_cache."""

    def _load(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        config.get_settings.cache_clear()
        return config.get_settings()

    yield _load
    config.get_settings.cache_clear()


# ── resolution ───────────────────────────────────────────────────────────────
def test_default_profile_is_full_and_fully_governed(load_settings):
    s = load_settings()  # no env → frozen default
    assert s.governance_profile == "full"
    assert s.govern_policy_enforcement
    assert s.govern_transactional_evidence
    assert s.govern_tombstone_propagation
    assert s.admission_gate_enabled and s.recall_gate_enabled and s.output_gate_enabled


def test_disabled_profile_turns_all_governance_off(load_settings):
    s = load_settings(MEMORYOPS_GOVERNANCE_PROFILE="disabled")
    assert s.governance_profile == "disabled"
    assert not s.govern_policy_enforcement
    assert not s.govern_transactional_evidence
    assert not s.govern_tombstone_propagation
    assert not s.admission_gate_enabled
    assert not s.recall_gate_enabled
    assert not s.output_gate_enabled


def test_single_control_ablation_leaves_profile_full(load_settings):
    s = load_settings(MEMORYOPS_ABLATE_TRANSACTIONAL_EVIDENCE="true")
    assert s.governance_profile == "full"
    assert s.govern_policy_enforcement  # untouched
    assert s.govern_tombstone_propagation  # untouched
    assert not s.govern_transactional_evidence  # the one ablated control


# ── behavioral: policy broker becomes permissive ─────────────────────────────
def test_policy_broker_blocks_secret_when_full_but_saves_when_disabled(load_settings):
    repo = InMemoryRepository()
    broker = PolicyBroker(repo)
    stored = repo.get_settings("t1", "u1")
    secret = CandidateMemory(content="my key is sk-ABCDEF012345678 keep it safe")

    load_settings()  # full
    assert broker.evaluate(
        secret, tenant_id="t1", user_id="u1", settings=stored
    ).decision == Decision.BLOCK

    load_settings(MEMORYOPS_GOVERNANCE_PROFILE="disabled")  # ungoverned
    assert broker.evaluate(
        secret, tenant_id="t1", user_id="u1", settings=stored
    ).decision == Decision.SAVE


# ── behavioral: transactional evidence off → no rollback ─────────────────────
def _ctx() -> WorkerContext:
    return WorkerContext(tenant_id="t1", user_id="u1", now=NOW)


def test_transaction_passthrough_when_evidence_disabled(load_settings):
    # The mirror of test_worker_atomicity: with transactional evidence OFF, a worker
    # mutation is NOT rolled back when its audit fails — proving the switch really
    # disables the atomic unit of work (the frozen default keeps it atomic).
    load_settings(MEMORYOPS_GOVERNANCE_PROFILE="disabled")
    repo = _CrashOnAction(MEMORY_DECAY_APPLIED)
    mem = seed_memory(repo, importance=8, age_days=300)

    result = DecayWorker(repo, age_threshold_days=90, importance_step=2).run(_ctx())

    assert repo.crashed
    assert result.status == WorkerRunStatus.failed.value
    # No transaction → the importance change persisted despite the audit failure.
    assert repo.get_memory("t1", "u1", mem.id).importance == 6
