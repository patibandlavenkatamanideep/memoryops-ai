import { Section, SectionIntro } from "../PublicShell";

/**
 * Capability categories that exist in the runtime today.
 *
 * Each entry names something the codebase implements — no roadmap items dressed as
 * features, no counts, no maturity badges. Where a capability has a limit worth
 * stating up front, it is stated here rather than discovered later: tamper-evidence
 * is not tamper-proofing, and governed deletion is not cryptographic erasure.
 */
const CAPABILITIES: { title: string; body: string }[] = [
  {
    title: "Governance",
    body: "A policy broker runs before every write and records an explicit verdict — save, defer to approval, block, drop or merge — with its reason, whether or not anything is stored.",
  },
  {
    title: "Memory types and state",
    body: "Memory is typed (preference, constraint, project, semantic, procedural and more) and moves through a lifecycle status rather than existing as undifferentiated text.",
  },
  {
    title: "Retention and deletion",
    body: "Retention windows by sensitivity tier, consent withdrawal, and legal hold that fails closed. Deletion is a governed state with a tombstone, and derived memory inherits it. This is governed erasure, not cryptographic shredding.",
  },
  {
    title: "Context admission",
    body: "Relevance is not sufficient. A memory enters the model's context only if it is also allowed, and each response carries a trace of what was admitted, withheld and why.",
  },
  {
    title: "Audit and evidence",
    body: "Every lifecycle mutation commits in the same transaction as its audit event, on a per-tenant hash chain. Read-only evidence reports can be produced per response, per deletion and per policy. Tamper-evident, which is not the same as tamper-proof.",
  },
  {
    title: "Tenant isolation",
    body: "Every query is scoped by tenant and user at the application layer, with Postgres row-level security enforced beneath it.",
  },
  {
    title: "Lifecycle loops",
    body: "Background work — decay, archival, retention, deletion compaction and verification, conflict scanning, reflection — runs off the request path as leased, retried, audited jobs.",
  },
  {
    title: "Evaluation",
    body: "Golden and adversarial suites, including deletion-leakage batteries that treat cross-session and derived-memory leakage as release-gating rather than advisory.",
  },
  {
    title: "Runtime integrations",
    body: "Swappable LLM, embedding and vector backends behind contracts, a typed Python SDK, and a framework-agnostic memory adapter for common agent frameworks.",
  },
];

export default function Capabilities() {
  return (
    <Section id="capabilities">
      <SectionIntro eyebrow="Capabilities" title="What the runtime does today">
        Implemented capability areas, with their limits stated where the distinction
        matters.
      </SectionIntro>

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {CAPABILITIES.map((capability) => (
          <article
            key={capability.title}
            className="rounded-panel border border-line bg-surface p-5"
          >
            <h3 className="text-sm font-semibold text-fg">{capability.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-fg-secondary">
              {capability.body}
            </p>
          </article>
        ))}
      </div>
    </Section>
  );
}
