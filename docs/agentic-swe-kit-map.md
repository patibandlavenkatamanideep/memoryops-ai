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
| 6 Memory Architecture | [phase-06](phase-gates/phase-06-memory-architecture.md) | Short/long-term, RAG, hybrid retrieval | 🟡 |
| 9 Evaluation Systems | [phase-09](phase-gates/phase-09-evaluation.md) | Golden + adversarial cases | ✅ |
| 10 Observability | [phase-10](phase-gates/phase-10-observability.md) | Traces, audit, latency, cost | 🟡 |
| 11 Security Architecture | [phase-11](phase-gates/phase-11-security.md) | Tenant isolation, PII, secret blocking | ✅ |
| 12 Reliability Engineering | [phase-12](phase-gates/phase-12-reliability.md) | Retries, breakers, degradation | ✅ |
| 15 Governance & Compliance | [phase-15](phase-gates/phase-15-governance.md) | Deletion, provenance, explainability | ✅ |
| 18 CI/CD for AI | [phase-18](phase-gates/phase-18-ci-cd-for-ai.md) | Invariant evidence gates | ✅ |
| 20 Continuous Learning | [phase-20](phase-gates/phase-20-continuous-learning.md) | Decay, reflection, feedback | 🟡 |

Legend: ✅ implemented · 🟡 scaffolded / partial.

The phases not listed (2–5, 7, 8, 13, 14, 16, 17, 19) are acknowledged but out of
scope for the current milestones; see [rollout.md](rollout.md).
