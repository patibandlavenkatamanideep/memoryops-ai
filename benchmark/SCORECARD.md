# MemoryOps AI — memory-governance scorecard (v2.2)

**Overall:** 50/50 (100%) · critical suites perfect: ✅

| Suite | Pass rate | Passed / Total | Critical |
| --- | --- | --- | --- |
| deletion_and_leakage | 100% | 12 / 12 | ★ |
| tenant_isolation | 100% | 17 / 17 | ★ |
| context_admission | 100% | 2 / 2 |  |
| policy_governance | 100% | 15 / 15 |  |
| retrieval_quality | 100% | 4 / 4 |  |

> Reproduce: `python benchmark/run_benchmark.py`. Cases live in `evals/` and run
> against an isolated, offline stub stack (no API keys). Bring your own memory
> system and score it on the same suites.
