import Link from "next/link";

import { NAV_GROUPS } from "@/components/shell/navigation";
import NavIcon from "@/components/shell/NavIcon";
import {
  Badge,
  Panel,
  PanelBody,
  PanelHeader,
  PageHeader,
  SectionHeader,
} from "@/components/ui";

/**
 * Control-plane overview.
 *
 * Static and claim-free: it describes the lifecycle MemoryOps implements and routes
 * to the surfaces that show real state. It renders no counts of its own — a landing
 * page full of numbers nobody fetched is exactly the fabricated-state problem the
 * rest of this UI exists to avoid.
 */

/** The lifecycle, in the product's own vocabulary. */
const LIFECYCLE = [
  { stage: "Capture", note: "Candidate memory is extracted from the turn." },
  { stage: "Evaluate", note: "The policy broker decides before anything is written." },
  { stage: "Store", note: "Typed, provenanced, tenant-scoped governed state." },
  { stage: "Retrieve", note: "Tenant-scoped candidate search. Deleted rows never surface." },
  { stage: "Rank", note: "Semantic, keyword, importance, recency, reinforcement." },
  { stage: "Compose", note: "Admitted memory becomes model context." },
  { stage: "Update", note: "Reinforcement, edits and conflict resolution." },
  { stage: "Forget", note: "Retention windows, consent withdrawal, soft delete." },
  { stage: "Audit", note: "Every mutation commits with its audit event." },
];

/** The guarantees the codebase enforces in tests — stated as behaviour, not as a badge. */
const INVARIANTS = [
  "Every memory query filters by tenant and user.",
  "Memories with status 'deleted' are never retrieved.",
  "Every memory carries a non-null source.",
  "Retrieval failure never blocks a response.",
  "The policy broker runs before any write.",
  "Temporary chat writes nothing and reads nothing.",
  "Each lifecycle mutation and its audit event commit together.",
];

const PLANES = [
  {
    title: "Write path",
    body: "Gateway → Extractor → Policy Broker → Write Service → Typed Store → Audit. Nothing is stored without an explicit, audited policy decision.",
  },
  {
    title: "Read path",
    body: "Retriever → Ranker → Admission Gate → Context Composer → Response. A memory enters context only if it is both relevant and allowed.",
  },
  {
    title: "Wrapping planes",
    body: "Security, Governance, Observability, Reliability and Evaluation wrap the lifecycle rather than sitting beside it.",
  },
];

export default function Home() {
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Overview"
        title="Govern what AI remembers."
        description="MemoryOps AI is a governed memory lifecycle for AI assistants — not a vector store with a chat box in front of it. Memory is typed, policy-gated, provenanced and auditable state."
      />

      <section className="space-y-3">
        <SectionHeader
          title="Lifecycle"
          description="The nine stages every candidate memory passes through."
        />
        <ol className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {LIFECYCLE.map((step, index) => (
            <li
              key={step.stage}
              className="flex gap-3 rounded-panel border border-line bg-surface px-3.5 py-3"
            >
              <span
                aria-hidden
                className="mt-0.5 font-mono text-xs text-fg-muted"
              >
                {String(index + 1).padStart(2, "0")}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-fg">{step.stage}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-fg-secondary">
                  {step.note}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="grid gap-3 lg:grid-cols-3">
        {PLANES.map((plane) => (
          <Panel key={plane.title}>
            <PanelHeader title={plane.title} />
            <PanelBody>
              <p className="text-sm leading-relaxed text-fg-secondary">{plane.body}</p>
            </PanelBody>
          </Panel>
        ))}
      </section>

      <section className="space-y-3">
        <SectionHeader
          title="Enforced invariants"
          description="Each of these is asserted in the API's test and eval suites, not asserted here."
        />
        <Panel>
          <PanelBody>
            <ul className="grid gap-2.5 sm:grid-cols-2">
              {INVARIANTS.map((invariant) => (
                <li key={invariant} className="flex gap-2.5 text-sm text-fg-secondary">
                  <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ok" />
                  <span className="leading-relaxed">{invariant}</span>
                </li>
              ))}
            </ul>
          </PanelBody>
        </Panel>
      </section>

      <section className="space-y-3">
        <SectionHeader
          title="Surfaces"
          description="Each of these renders live state from the API for the tenant you are operating on."
        />
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {NAV_GROUPS.flatMap((group) =>
            group.items
              .filter((item) => item.href !== "/")
              .map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="group flex gap-3 rounded-panel border border-line bg-surface px-3.5 py-3 transition-colors hover:border-line-strong hover:bg-surface-raised"
                >
                  <span className="mt-0.5 text-fg-muted group-hover:text-accent-strong">
                    <NavIcon glyph={item.glyph} />
                  </span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-2 text-sm font-medium text-fg">
                      {item.label}
                      <Badge tone="quiet" className="font-mono text-[10px]">
                        {group.label}
                      </Badge>
                    </span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-fg-secondary">
                      {item.summary}
                    </span>
                  </span>
                </Link>
              )),
          )}
        </div>
      </section>
    </div>
  );
}
