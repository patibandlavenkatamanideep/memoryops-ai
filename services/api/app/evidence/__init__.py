"""Enterprise Evidence Layer (v2.0, ADR-024).

Tamper-evident audit hash chain + security-reviewable evidence reports (per-response
bundles, deletion proofs, policy reports, lifecycle exports). Makes MemoryOps'
governance verifiable, not just claimed.
"""

from __future__ import annotations

from .hashchain import GENESIS, compute_entry_hash, verify_chain
from .reports import (
    deletion_proof,
    evidence_bundle,
    lifecycle_export,
    policy_report,
    verify_audit,
)

__all__ = [
    "GENESIS",
    "compute_entry_hash",
    "verify_chain",
    "verify_audit",
    "evidence_bundle",
    "deletion_proof",
    "policy_report",
    "lifecycle_export",
]
