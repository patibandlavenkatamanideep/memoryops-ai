import type { ReactNode } from "react";

import { cn } from "./cn";

/**
 * Value treatments: ids, opaque identifiers, key/value pairs and quoted source text.
 *
 * Identifiers are the control plane's primary currency — memory ids, trace ids, loop
 * run ids — and they were previously rendered a different way on every screen
 * (`slice(0, 8)` here, full uuid there, sometimes neither monospaced nor selectable).
 * Truncation now always keeps the full value in `title` and in the copyable DOM text
 * so an operator correlating an id against API logs never gets a shortened one.
 */

export function Code({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <code
      className={cn(
        "rounded border border-line bg-surface-sunken px-1.5 py-0.5 font-mono text-[0.8125rem] text-fg-secondary",
        className,
      )}
    >
      {children}
    </code>
  );
}

/**
 * A shortened identifier that still carries its full value.
 *
 * The visible text is truncated by CSS, not by `slice`, so selecting and copying the
 * element yields the complete id.
 */
export function MonoId({
  value,
  chars = 8,
  className,
  label,
}: {
  value: string;
  /** Rendered width, in characters. The DOM text is always the full value. */
  chars?: number;
  className?: string;
  /** Prefix such as "trace" or "memory". */
  label?: string;
}) {
  return (
    <span className={cn("inline-flex min-w-0 items-baseline gap-1 text-xs", className)}>
      {label ? <span className="text-fg-muted">{label}</span> : null}
      <span
        title={value}
        className="inline-block overflow-hidden text-ellipsis whitespace-nowrap align-bottom font-mono text-fg-muted"
        style={{ maxWidth: `${chars}ch` }}
      >
        {value}
      </span>
    </span>
  );
}

/** Key/value pair. Renders as a `<div>` so it can sit inside a `<dl>` grid. */
export function KeyValue({
  label,
  children,
  className,
  mono = false,
}: {
  label: string;
  children: ReactNode;
  className?: string;
  mono?: boolean;
}) {
  return (
    <div className={cn("min-w-0 space-y-0.5", className)}>
      <dt className="text-label uppercase text-fg-muted">{label}</dt>
      <dd className={cn("break-words text-sm text-fg", mono && "font-mono text-xs")}>
        {children}
      </dd>
    </div>
  );
}

export function DefinitionList({
  children,
  className,
  columns = 2,
}: {
  children: ReactNode;
  className?: string;
  columns?: 1 | 2 | 3;
}) {
  const cols = {
    1: "",
    2: "sm:grid-cols-2",
    3: "sm:grid-cols-2 lg:grid-cols-3",
  }[columns];
  return <dl className={cn("grid gap-x-6 gap-y-4", cols, className)}>{children}</dl>;
}

/** Quoted provenance excerpt — source text, visually distinct from governed content. */
export function SourceQuote({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <blockquote
      className={cn(
        "border-l-2 border-line-strong bg-surface-sunken/60 py-2 pl-3 pr-2 text-sm italic text-fg-secondary",
        className,
      )}
    >
      {children}
    </blockquote>
  );
}

/**
 * Numeric score with a proportional bar.
 *
 * Only for values the API returns on a known 0–1 scale (ranker score breakdowns).
 * The bar is `aria-hidden`; the number beside it is the accessible value.
 */
export function ScoreBar({
  label,
  value,
  className,
}: {
  label: string;
  value: number;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className={cn("min-w-[7.5rem] space-y-1", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[11px] text-fg-muted">{label}</span>
        <span className="font-mono text-[11px] text-fg-secondary">{value.toFixed(2)}</span>
      </div>
      <div aria-hidden className="h-1 overflow-hidden rounded-full bg-surface-hover">
        <div className="h-full rounded-full bg-accent/70" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
