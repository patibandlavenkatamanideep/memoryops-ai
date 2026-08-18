import type { ReactNode } from "react";

import { Badge, cn } from "@/components/ui";

/**
 * The label that separates worked examples from product claims.
 *
 * Everything on the public page that shows a *specific* memory, verdict or trace is
 * invented for explanation. None of it came from a running MemoryOps instance, and
 * a visitor must not have to work that out. So the label is a required prop on the
 * wrapper rather than an optional decoration a section can forget to pass — the
 * only way to render a walkthrough here is to say what it is.
 *
 * There are no counters, adoption figures, customer names, benchmark results,
 * latency numbers or compliance marks anywhere on this page, illustrative or
 * otherwise. Those would be fabrications, not illustrations, and no label makes
 * them acceptable.
 */
export type IllustrativeKind = "Illustrative" | "Example" | "Simulation";

export function IllustrativeBadge({
  kind,
  className,
}: {
  kind: IllustrativeKind;
  className?: string;
}) {
  return (
    <Badge tone="warn" className={cn("shrink-0", className)}>
      {kind}
    </Badge>
  );
}

/**
 * Wraps a worked example. The label sits inside the same bordered region as the
 * content, so it cannot be scrolled away from or read as belonging to a neighbour.
 */
export function IllustrativeBlock({
  kind,
  note,
  children,
  className,
}: {
  kind: IllustrativeKind;
  /** What specifically is invented, in one line. Required — "Illustrative" alone is vague. */
  note: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-panel border border-warn/30 bg-warn/[0.03]",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-warn/25 bg-warn/[0.06] px-4 py-2.5">
        <IllustrativeBadge kind={kind} />
        <p className="text-xs leading-relaxed text-fg-secondary">{note}</p>
      </div>
      <div className="p-4 sm:p-5">{children}</div>
    </div>
  );
}
