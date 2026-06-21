# Phase 4 - Workflow Orchestration

**Question:** Are important workflows modeled as explicit, observable loops?

## MemoryOps mapping

MemoryOps v0.2.2 introduces loop engineering as a typed architecture layer.
The six primary loops are registered in `services/api/app/loops/registry.py`:
`memory.write`, `memory.read`, `memory.governance`, `memory.evaluation`,
`release.gate`, and `learning.continuous`.

## Gate (must be true to pass)

- Loop definitions have states, policy gates, failure modes, fallback behavior,
  audit events, and required evidence.
- Loop transitions are validated by a state machine.
- Read/write/governance paths emit loop runs and loop events.
- Loop metadata avoids raw secrets and full user messages.
- API/UI expose loop definitions and recent loop evidence.

## Evidence

- `services/api/app/loops/`
- `services/api/tests/test_loop_*.py`
- `services/api/tests/test_memory_write_loop.py`
- `services/api/tests/test_memory_read_loop.py`
- [docs/loop-engineering.md](../loop-engineering.md)
- [docs/loop-contracts.md](../loop-contracts.md)

## Status: Implemented (v0.2.2)
