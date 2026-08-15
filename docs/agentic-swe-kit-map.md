# agentic-swe-kit Phase-Gate Map

MemoryOps AI uses [agentic-swe-kit](https://github.com/ayush488-glitch/agentic-swe-kit)
as a **phase-gate review framework**. Each major feature passes through (and
updates) the relevant gate in [`phase-gates/`](phase-gates/). A gate is "green"
only when its stated conditions are true.

## Diagnostic (run before picking a phase)

1. New project, existing codebase, or live incident?
2. Any AI / LLM components involved?
3. Distributed or multi-service?
4. Auth or sensitive data in scope?
5. Which lifecycle phase is the project in?

## Mapping

| Phase | Gate file | MemoryOps focus | Status |
|---|---|---|---|
| 0 Cognitive Design | [phase-00](phase-gates/phase-00-cognitive-design.md) | What should memory decide? | ✅ |
| 1 System Architecture | [phase-01](phase-gates/phase-01-system-architecture.md) | Service boundaries & invariants | ✅ |
| 4 Workflow Orchestration | [phase-04](phase-gates/phase-04-workflow-orchestration.md) | Loop definitions, transitions, evidence | ✅ |
| 5 LLM Reasoning | [phase-05](phase-gates/phase-05-llm-reasoning.md) | Provider adapters, structured intelligence | ✅ |
| 6 Memory Architecture | [phase-06](phase-gates/phase-06-memory-architecture.md) | Short/long-term, RAG, hybrid retrieval | 🟡 |
| 6 Human-in-the-Loop | [phase-06-hitl](phase-gates/phase-06-human-in-the-loop.md) | Memory control plane: inspect, approve, correct | ✅ |
| 9 Evaluation Systems | [phase-09](phase-gates/phase-09-evaluation.md) | Golden + adversarial cases | ✅ |
| 10 Observability | [phase-10](phase-gates/phase-10-observability.md) | Traces, audit, latency, cost | 🟡 |
| 11 Security Architecture | [phase-11](phase-gates/phase-11-security.md) | Tenant isolation, PII, secret blocking | ✅ |
| 12 Reliability Engineering | [phase-12](phase-gates/phase-12-reliability.md) | Retries, breakers, degradation | ✅ |
| 12 Lifecycle Workers *(addendum)* | [phase-12-workers](phase-gates/phase-12-background-lifecycle-workers.md) | Background decay/archive/retention jobs | ✅ |
| 13 Infrastructure & Deployment | [phase-13](phase-gates/phase-13-infrastructure.md) | Build, ship, run in production (Railway) | ✅ |
| 13 Deletion Compaction *(addendum)* | [phase-13-purge](phase-gates/phase-13-deletion-compaction-vector-purge.md) | Content/vector purge + verification | ✅ |
| 14 Worker Runtime *(addendum)* | [phase-14](phase-gates/phase-14-worker-runtime-orchestration.md) | Leases, retries, scheduling, dead-letter | ✅ |
| 15 Governance & Compliance | [phase-15](phase-gates/phase-15-governance.md) | Deletion, provenance, explainability | ✅ |
| 16 Economics & Cost Control | [phase-16](phase-gates/phase-16-economics.md) | Token/cost accounting, compression | ✅ |
| 18 CI/CD for AI | [phase-18](phase-gates/phase-18-ci-cd-for-ai.md) | Invariant evidence gates | ✅ |
| 20 Continuous Learning | [phase-20](phase-gates/phase-20-continuous-learning.md) | Decay, reflection, feedback | 🟡 |

Legend: ✅ implemented · 🟡 scaffolded / partial.

Every file in [`phase-gates/`](phase-gates/) is listed above. Several gates are
enforced: `scripts/pr_invariant_gate.py` names specific gate files as required
evidence, so a change in those areas fails CI without its gate update. That is why
gate files stay in place rather than being archived when the work they describe
ships — they remain the live evidence target.

The phases not listed (2, 3, 7, 8, 17, 19) are acknowledged but out of scope for the
current milestones; see [rollout.md](rollout.md).
