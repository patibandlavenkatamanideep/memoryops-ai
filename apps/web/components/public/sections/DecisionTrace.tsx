import { Badge, Code } from "@/components/ui";
import { IllustrativeBlock } from "../Illustrative";
import { Section, SectionIntro } from "../PublicShell";

/**
 * One concrete memory decision, end to end.
 *
 * This is the section that has to land. A visitor who has just read "governed
 * memory layer" needs to see what a governed decision actually *is* before any
 * lifecycle vocabulary arrives — so this comes second, before Lifecycle and
 * Governance, and follows a single message through the whole runtime rather than
 * describing the stages abstractly.
 *
 * Every value shown is invented. That is what `IllustrativeBlock` declares.
 */

type Verdict = "SAVE" | "SESSION ONLY" | "BLOCK";

const VERDICT_TONE = {
  SAVE: "ok",
  "SESSION ONLY": "info",
  BLOCK: "danger",
} as const;

const STEPS: {
  stage: string;
  detail: string;
  body?: React.ReactNode;
}[] = [
  {
    stage: "1 · Message",
    detail: "A turn arrives from the assistant's session.",
    body: (
      <p className="rounded-lg border border-line bg-surface-sunken p-3 text-sm leading-relaxed text-fg">
        &ldquo;We run Postgres 16 on RDS. Always have two people review a migration
        before it ships. My AWS key is <span className="text-danger">AKIA…</span> if
        you need it.&rdquo;
      </p>
    ),
  },
  {
    stage: "2 · Capture",
    detail: "The extractor proposes candidate memories. Nothing is stored yet.",
  },
  {
    stage: "3 · Evaluate",
    detail:
      "The policy broker decides on each candidate, before any write. Its verdict is the record.",
  },
  {
    stage: "4 · Store",
    detail:
      "Only admitted candidates become typed, provenanced, tenant-scoped state.",
  },
  {
    stage: "5 · Retrieve & admit",
    detail:
      "On a later turn, retrieval is scoped to the tenant and the admission gate decides what may enter context.",
  },
  {
    stage: "6 · Audit",
    detail:
      "The mutation and its audit event commit together, so the record cannot disagree with what happened.",
  },
];

const CANDIDATES: {
  content: string;
  type: string;
  verdict: Verdict;
  reason: string;
}[] = [
  {
    content: "Team runs Postgres 16 on RDS.",
    type: "project",
    verdict: "SAVE",
    reason: "Durable, low-sensitivity project fact. Useful beyond this session.",
  },
  {
    content: "Migrations require two-person review before shipping.",
    type: "constraint",
    verdict: "SAVE",
    reason: "Stable working agreement. Stored as a constraint, not a preference.",
  },
  {
    content: "AWS access key AKIA…",
    type: "credential",
    verdict: "BLOCK",
    reason:
      "Credential-shaped content is refused at the broker. It is never written, so it can never be retrieved.",
  },
];

export default function DecisionTrace() {
  return (
    <Section id="decision-trace">
      <SectionIntro eyebrow="How it works" title="One message, one governed decision">
        Memory is not a side effect of a conversation. Each candidate is evaluated
        on its own, and the verdict — with its reason — is what gets recorded.
      </SectionIntro>

      <IllustrativeBlock
        kind="Illustrative"
        note="A worked example. The message, candidates, verdicts and reasons below are written for explanation and did not come from a running instance."
      >
        <div className="grid gap-8 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          <ol className="space-y-5 border-l border-line pl-5">
            {STEPS.map((step) => (
              <li key={step.stage} className="relative space-y-2">
                <span
                  aria-hidden
                  className="absolute -left-[1.4375rem] top-1.5 h-2 w-2 rounded-full bg-accent ring-4 ring-canvas"
                />
                <p className="text-sm font-medium text-fg">{step.stage}</p>
                <p className="text-xs leading-relaxed text-fg-secondary">
                  {step.detail}
                </p>
                {step.body}
              </li>
            ))}
          </ol>

          <div className="space-y-5">
            <div className="space-y-3">
              <p className="text-label uppercase text-fg-muted">
                Broker verdicts · 3 candidates
              </p>
              <ul className="space-y-2.5">
                {CANDIDATES.map((c) => (
                  <li
                    key={c.content}
                    className="rounded-lg border border-line bg-surface p-3.5"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="min-w-0 break-words text-sm text-fg">{c.content}</p>
                      <Badge tone={VERDICT_TONE[c.verdict]}>{c.verdict}</Badge>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Badge tone="quiet">{c.type}</Badge>
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-fg-muted">
                      {c.reason}
                    </p>
                  </li>
                ))}
              </ul>
            </div>

            <div className="rounded-lg border border-line bg-surface p-4">
              <p className="text-label uppercase text-fg-muted">
                A later turn: &ldquo;draft the migration plan&rdquo;
              </p>
              <ul className="mt-3 space-y-2 text-sm leading-relaxed text-fg-secondary">
                <li className="flex gap-2.5">
                  <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ok" />
                  <span>
                    Both saved memories are retrieved and admitted, and the answer is
                    shaped by the two-person review constraint.
                  </span>
                </li>
                <li className="flex gap-2.5">
                  <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-danger" />
                  <span>
                    The credential is not retrieved, because it was never stored.
                  </span>
                </li>
                <li className="flex gap-2.5">
                  <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-info" />
                  <span>
                    The response carries a trace naming which memories entered context
                    and why — <Code>memory_retrieved</Code>, <Code>memory_blocked</Code>{" "}
                    and the rest land in the audit log.
                  </span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </IllustrativeBlock>
    </Section>
  );
}
