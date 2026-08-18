import { cn } from "@/components/ui";
import { Section, SectionIntro } from "../PublicShell";

/**
 * Architectural contrast, not a competitive claim.
 *
 * The left column describes the *direct-write pattern* — an agent appending text
 * straight into a retrieval index — because that is a real architecture with real
 * consequences, and it is what MemoryOps is shaped against. It deliberately names
 * no product and makes no claim about how any particular system behaves. Plenty of
 * memory tools do more than this; the point is the pattern, not the field.
 *
 * The closing line says so outright, so the section cannot be read as a scoreboard.
 */

const DIRECT = {
  title: "Direct-write memory",
  summary: "The agent appends to a retrieval index. The index is the system of record.",
  points: [
    "Any text the model produces can become memory.",
    "There is no separate decision to inspect later — the write *is* the decision.",
    "Retrieval returns whatever is nearest in vector space.",
    "Deletion is a best-effort index operation; derived copies are not tracked.",
    "Why a memory exists, and why it influenced an answer, is not recorded.",
  ],
};

const GOVERNED = {
  title: "Governed memory",
  summary:
    "A policy broker decides before any write. Storage holds typed state; evidence is a first-class output.",
  points: [
    "Every candidate gets an explicit verdict — save, defer, block, drop, merge.",
    "The verdict and its reason are recorded whether or not anything is stored.",
    "Retrieval is tenant- and user-scoped, and an admission gate decides what enters context.",
    "Deletion is a governed state with a tombstone; derived artefacts inherit it.",
    "Provenance on every memory, and a trace explaining every memory used.",
  ],
};

function Column({
  data,
  tone,
  label,
}: {
  data: typeof DIRECT;
  tone: "muted" | "accent";
  label: string;
}) {
  return (
    <div
      className={cn(
        "flex h-full flex-col gap-4 rounded-panel border p-5",
        tone === "accent" ? "border-accent/35 bg-accent/[0.04]" : "border-line bg-surface",
      )}
    >
      <div className="space-y-2">
        <p
          className={cn(
            "text-label uppercase",
            tone === "accent" ? "text-accent-strong" : "text-fg-muted",
          )}
        >
          {label}
        </p>
        <h3 className="text-lg font-semibold tracking-tight text-fg">{data.title}</h3>
        <p className="text-sm leading-relaxed text-fg-secondary">{data.summary}</p>
      </div>
      <ul className="space-y-2.5">
        {data.points.map((point) => (
          <li key={point} className="flex gap-2.5 text-sm leading-relaxed text-fg-secondary">
            <span
              aria-hidden
              className={cn(
                "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                tone === "accent" ? "bg-ok" : "bg-line-strong",
              )}
            />
            <span>{point}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function BeforeWith() {
  return (
    <Section>
      <SectionIntro eyebrow="Architecture" title="Two ways to give a model memory">
        The difference is not how text is stored. It is whether a decision exists
        between producing a memory and being able to retrieve it.
      </SectionIntro>

      <div className="grid gap-4 lg:grid-cols-2">
        <Column data={DIRECT} tone="muted" label="Pattern" />
        <Column data={GOVERNED} tone="accent" label="MemoryOps" />
      </div>

      <p className="mt-6 max-w-3xl text-xs leading-relaxed text-fg-muted">
        This contrasts two architectures, not two products. &ldquo;Direct-write
        memory&rdquo; describes a pattern — writing straight into a retrieval index —
        and is not a claim about how any specific system behaves. Many tools sit
        somewhere between these columns.
      </p>
    </Section>
  );
}
