import { Section, SectionIntro } from "../PublicShell";

/**
 * The nine lifecycle stages, in the product's own vocabulary.
 *
 * These are the stage names the codebase uses, not a marketing rewrite of them, so
 * a reader who goes on to the docs or the API meets the same words.
 */
const STAGES: { stage: string; note: string }[] = [
  { stage: "Capture", note: "Candidate memories are extracted from the turn." },
  { stage: "Evaluate", note: "The policy broker decides before anything is written." },
  { stage: "Store", note: "Typed, provenanced, tenant-scoped governed state." },
  { stage: "Retrieve", note: "Scoped candidate search. Deleted memory never surfaces." },
  { stage: "Rank", note: "Semantic, keyword, importance, recency, reinforcement." },
  { stage: "Compose", note: "An admission gate decides what becomes model context." },
  { stage: "Update", note: "Reinforcement, edits and conflict resolution." },
  { stage: "Forget", note: "Retention windows, consent withdrawal, governed deletion." },
  { stage: "Audit", note: "Every mutation commits together with its audit event." },
];

export default function Lifecycle() {
  return (
    <Section id="lifecycle">
      <SectionIntro eyebrow="Lifecycle" title="Nine stages, each one governed">
        Memory has a lifecycle whether or not a system models it. MemoryOps models it
        explicitly, so each stage is a place where policy applies and evidence is
        produced.
      </SectionIntro>

      <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {STAGES.map((step, index) => (
          <li
            key={step.stage}
            className="flex gap-3.5 rounded-panel border border-line bg-surface p-4"
          >
            <span
              aria-hidden
              className="mt-0.5 font-mono text-xs text-fg-muted"
            >
              {String(index + 1).padStart(2, "0")}
            </span>
            <div className="min-w-0 space-y-1">
              <h3 className="text-sm font-medium text-fg">{step.stage}</h3>
              <p className="text-xs leading-relaxed text-fg-secondary">{step.note}</p>
            </div>
          </li>
        ))}
      </ol>
    </Section>
  );
}
