import { PageHeader, Panel, PanelBody, PanelHeader, SectionHeader } from "@/components/ui";

/**
 * Public architecture reference.
 *
 * Also the web service's Railway healthcheck target (`railway/web.railway.json`), which
 * constrains it in one important way: it must stay a static server component with no
 * data fetching and no session dependency, so a degraded API or an unauthenticated
 * probe still gets a 200. Adding a `fetch` here would make deploys fail whenever the
 * API is the thing that is unhealthy.
 *
 * Content is unchanged in this revision — only its presentation moved onto the shared
 * design system.
 */

const sections = [
  {
    title: "Write path",
    body: "Gateway → Extractor → Policy Broker → Write Service → Typed Store → Audit. The policy broker is the choke point: secrets are blocked, sensitive content goes to an approval queue, low-utility is dropped, duplicates reinforce existing memory. Nothing is stored without an audited decision.",
  },
  {
    title: "Read path",
    body: "Retriever (hybrid: vector + keyword) → Ranker (0.35 semantic + 0.20 keyword + 0.15 importance + 0.10 recency + 0.10 confidence + 0.10 reinforcement) → Context Composer → Response. Deleted and pending memories are never retrieved. Retrieval failures degrade gracefully.",
  },
  {
    title: "Background jobs",
    body: "Decay ages out memory weights, archival retires low-weight memories, conflict resolution reconciles contradictions, reflection/compression collapses repeats. Jobs share the repository interface so they can move to Celery/Temporal.",
  },
  {
    title: "Security plane",
    body: "Tenant + user scoping on every query, RLS-ready schema, secret/PII detection, prompt-injection guard, temporary chat, soft-delete with a retrieval-exclusion guarantee.",
  },
  {
    title: "Governance plane",
    body: "Typed lifecycle states, approve/reject/edit/archive/delete, append-only audit, provenance on every memory, explainable memory-used badges.",
  },
  {
    title: "Observability plane",
    body: "Structured JSON logs with per-request trace_id and secret redaction, latency + memory counts, metrics surfaced on the admin dashboard. OpenTelemetry / Prometheus / Langfuse on the roadmap.",
  },
];

const invariants = [
  "User A's memory is never returned to User B or another tenant.",
  "Deleted memories are never retrieved again.",
  "Every stored memory traces back to its source.",
  "Memory retrieval failure never blocks a response.",
  "Unsafe / secret-like content is filtered before storage.",
  "Temporary sessions never write or retrieve memory.",
  "Every lifecycle event produces an append-only audit event.",
];

export default function ArchitecturePage() {
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Reference"
        title="Architecture"
        description="How the governed memory runtime is put together: the two request paths, the background lifecycle, and the planes that wrap them."
      />

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {sections.map((s) => (
          <Panel key={s.title}>
            <PanelHeader title={s.title} />
            <PanelBody>
              <p className="text-sm leading-relaxed text-fg-secondary">{s.body}</p>
            </PanelBody>
          </Panel>
        ))}
      </section>

      <section className="space-y-3">
        <SectionHeader
          title="Enterprise invariants"
          description="Enforced in the API's code and asserted by its test and eval suites."
        />
        <Panel>
          <PanelBody>
            <ul className="grid gap-2.5 sm:grid-cols-2">
              {invariants.map((i) => (
                <li key={i} className="flex gap-2.5 text-sm text-fg-secondary">
                  <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ok" />
                  <span className="leading-relaxed">{i}</span>
                </li>
              ))}
            </ul>
          </PanelBody>
        </Panel>
      </section>

      <Panel>
        <PanelHeader title="Production upgrade path" />
        <PanelBody>
          <p className="text-sm leading-relaxed text-fg-secondary">
            Heuristic LLM/embeddings → provider adapters. RLS enabled → enforced. Soft
            delete → crypto-shred retention worker. Logs → OpenTelemetry traces +
            Prometheus metrics + Langfuse. In-memory store → Postgres + pgvector. Loop
            worker → Celery/Temporal with retries + DLQs.
          </p>
        </PanelBody>
      </Panel>
    </div>
  );
}
