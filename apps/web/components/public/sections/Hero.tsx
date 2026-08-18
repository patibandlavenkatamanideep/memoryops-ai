import Link from "next/link";

/**
 * First screen.
 *
 * One job: a visitor should leave it knowing MemoryOps is a governed memory layer
 * for AI systems — not a vector database, not a chatbot. So the headline states the
 * promise, the paragraph names the category in its first clause, and the strip
 * underneath is the write path in six words rather than a feature list.
 *
 * No metrics, no logos, no badges. There is nothing true to put there yet, and a
 * placeholder would be a fabrication.
 */

/**
 * The path a memory travels, compressed. Stage names from the runtime, not
 * marketing nouns — and not invented data, so it needs no illustrative label.
 *
 * Rendered as a vertical rail rather than a horizontal chip row: horizontally it
 * wrapped mid-sequence at tablet widths, orphaning a leading "→" on its own line,
 * and it left the right half of the hero empty on wide screens.
 */
const PATH: { step: string; note: string }[] = [
  { step: "Candidate", note: "Extracted from the turn" },
  { step: "Policy decision", note: "Before any write" },
  { step: "Typed state", note: "Provenanced, tenant-scoped" },
  { step: "Scoped retrieval", note: "Deleted memory never surfaces" },
  { step: "Admission", note: "Relevant and allowed" },
  { step: "Evidence", note: "Committed with the mutation" },
];

export default function Hero() {
  return (
    <section className="px-5 pb-16 pt-16 sm:px-8 sm:pb-20 sm:pt-24">
      <div className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)] lg:items-start lg:gap-16">
        <div className="max-w-3xl space-y-6">
          <p className="text-label uppercase text-accent-strong">
            Governed memory runtime
          </p>

          <h1 className="text-4xl font-semibold leading-[1.1] tracking-tight text-fg sm:text-5xl lg:text-6xl">
            Govern what AI remembers.
          </h1>

          <p className="text-lg leading-relaxed text-fg-secondary">
            MemoryOps AI is a governed memory layer for AI assistants and agents.
            Every candidate memory passes a policy decision before it is stored, every
            stored memory is typed and traceable to its source, and every memory that
            reaches the model&apos;s context leaves an audit record explaining why.
          </p>

          <p className="text-base leading-relaxed text-fg-muted">
            Most memory systems are a vector store with writes in front of them.
            MemoryOps treats memory as governed state: something that is admitted,
            explained, retained, forgotten and evidenced on purpose.
          </p>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Link
              href="/chat"
              className="inline-flex h-11 items-center justify-center rounded-lg bg-accent px-5 text-sm font-medium text-canvas transition-colors hover:bg-accent-strong"
            >
              Open control plane
            </Link>
            {/*
             * Secondary CTA stays on this page. The technical architecture reference
             * lives behind a clearly-labelled link further down, so a visitor is never
             * moved into the operator-facing shell by the hero.
             */}
            <a
              href="#decision-trace"
              className="inline-flex h-11 items-center justify-center rounded-lg border border-line-strong bg-surface-raised px-5 text-sm font-medium text-fg transition-colors hover:bg-surface-hover"
            >
              See a memory decision
            </a>
          </div>
        </div>

        <div className="rounded-panel border border-line bg-surface p-5">
          <p className="text-label uppercase text-fg-muted">Path of a memory</p>
          <ol className="mt-4 space-y-4 border-l border-line pl-5">
            {PATH.map((entry) => (
              <li key={entry.step} className="relative">
                <span
                  aria-hidden
                  className="absolute -left-[1.4375rem] top-1.5 h-2 w-2 rounded-full bg-accent/70 ring-4 ring-surface"
                />
                <p className="text-sm font-medium text-fg">{entry.step}</p>
                <p className="text-xs leading-relaxed text-fg-muted">{entry.note}</p>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
