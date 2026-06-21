# Phase 20 — Continuous Learning

**Question:** Feedback loops, reflection vs learning, memory evolution.

## MemoryOps mapping
Background worker evolves memory over time: decay ages out weights, archival
retires low-weight memories, conflict detection finds contradictions, and
reflection/compression (stub) collapses repeats. A `memory_feedback` table feeds
quality signals back into ranking and evals. v0.2.2 records the worker skeleton
as `learning.continuous` loop evidence.

## Gate (must be true to pass)
- Memory weight decays with age and is reinforced by repetition.
- Low-weight memory is archived (not silently lost), with an audit trail.
- A feedback signal exists and can inform decay/ranking.
- Worker runs emit loop events for decay, archive, conflict detection,
  compression, and reflection stubs.

## Evidence
- `services/worker/jobs.py` (decay / archive / conflict / reflect)
- `services/api/app/loops/registry.py` (`learning.continuous`)
- `infra/db/migrations/002_core_tables.sql` (`memory_feedback`)
- `services/api/app/services/ranker.py` (reinforcement term)

## Gaps to close (→ v0.5)
- Real scheduler (Celery/Temporal), reflection/compression logic, feedback wired
  into the UI and into eval regeneration.

## Status: 🟡 Scaffolded
