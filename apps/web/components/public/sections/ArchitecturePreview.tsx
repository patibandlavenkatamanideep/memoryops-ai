import Link from "next/link";

import { Section, SectionIntro } from "../PublicShell";

/**
 * Self-contained architecture summary.
 *
 * Self-contained on purpose: `/architecture` is the operator-facing technical
 * reference and still renders inside the control-plane shell, so sending a visitor
 * there from this page would drop them into a different chrome without warning. The
 * link out is secondary and explicitly labelled as a technical/system view, so the
 * transition is expected rather than surprising.
 *
 * Component names match the codebase — Gateway, Extractor, Policy Broker, Retriever,
 * Ranker, Admission Gate, Context Composer — so this stays a smaller view of the
 * same system rather than a parallel description of it.
 */

const WRITE_PATH = [
  "Gateway",
  "Extractor",
  "Policy Broker",
  "Write Service",
  "Typed Store",
  "Audit",
];

const READ_PATH = [
  "Retriever",
  "Ranker",
  "Admission Gate",
  "Context Composer",
  "Response",
];

const PLANES: { name: string; body: string }[] = [
  {
    name: "Security",
    body: "Tenant and user scoping on every query, row-level security beneath it, secret detection before storage.",
  },
  {
    name: "Governance",
    body: "Typed lifecycle states, approval queue, retention, legal hold, consent.",
  },
  {
    name: "Observability",
    body: "Structured logs, per-request traces, Prometheus metrics.",
  },
  {
    name: "Reliability",
    body: "Retrieval failure degrades instead of blocking a response; background jobs lease, retry and dead-letter.",
  },
  {
    name: "Evaluation",
    body: "Golden and adversarial suites gate releases on the invariants that matter.",
  },
];

function Path({
  label,
  steps,
  note,
}: {
  label: string;
  steps: string[];
  note: string;
}) {
  return (
    <div className="rounded-panel border border-line bg-surface p-5">
      <h3 className="text-sm font-semibold text-fg">{label}</h3>
      <ol className="mt-3.5 flex flex-wrap items-center gap-x-1.5 gap-y-2">
        {steps.map((step, i) => (
          <li key={step} className="flex items-center gap-1.5">
            {i > 0 ? (
              <span aria-hidden className="text-line-strong">
                →
              </span>
            ) : null}
            <span className="rounded-md border border-line bg-surface-raised px-2.5 py-1 text-xs text-fg-secondary">
              {step}
            </span>
          </li>
        ))}
      </ol>
      <p className="mt-3.5 text-xs leading-relaxed text-fg-muted">{note}</p>
    </div>
  );
}

export default function ArchitecturePreview() {
  return (
    <Section id="architecture-preview">
      <SectionIntro eyebrow="System" title="How it is put together">
        Two request paths and five planes that wrap them. The planes are not a layer
        beside the lifecycle — every stage passes through all of them.
      </SectionIntro>

      <div className="grid gap-4 lg:grid-cols-2">
        <Path
          label="Write path"
          steps={WRITE_PATH}
          note="The policy broker is the choke point. Nothing reaches the store without an audited decision."
        />
        <Path
          label="Read path"
          steps={READ_PATH}
          note="Deleted memory is never retrieved, and retrieval failure degrades rather than blocking the response."
        />
      </div>

      <div className="mt-4 rounded-panel border border-line bg-surface p-5">
        <h3 className="text-sm font-semibold text-fg">Wrapping planes</h3>
        <dl className="mt-4 grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
          {PLANES.map((plane) => (
            <div key={plane.name} className="space-y-1">
              <dt className="text-xs font-medium text-accent-strong">{plane.name}</dt>
              <dd className="text-xs leading-relaxed text-fg-secondary">{plane.body}</dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="mt-8 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-6">
        <Link
          href="/chat"
          className="inline-flex h-10 items-center justify-center rounded-lg bg-accent px-5 text-sm font-medium text-canvas transition-colors hover:bg-accent-strong"
        >
          Open control plane
        </Link>
        {/* Secondary and explicitly labelled: this leaves the product page for the
            operator-facing technical reference, which renders in a different shell. */}
        <Link
          href="/architecture"
          className="inline-flex min-h-[2.5rem] items-center rounded-sm text-sm text-fg-secondary underline-offset-4 hover:text-fg hover:underline"
        >
          View the technical architecture reference →
        </Link>
        <span className="text-xs text-fg-muted">
          Detailed system view, written for engineers and operators.
        </span>
      </div>
    </Section>
  );
}
