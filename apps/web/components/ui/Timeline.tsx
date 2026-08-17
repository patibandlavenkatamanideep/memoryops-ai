import type { ReactNode } from "react";

import { cn } from "./cn";
import type { Tone } from "./Badge";

/**
 * Ordered event timeline — audit history, loop events, lifecycle transitions.
 *
 * An `<ol>` because the ordering carries meaning: this is an append-only record, and
 * "newest first" is a fact about the data, not a visual arrangement.
 */

const DOT_TONES: Record<Tone, string> = {
  neutral: "bg-neutral",
  accent: "bg-accent",
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  info: "bg-info",
  quiet: "bg-line-strong",
};

export function Timeline({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <ol className={cn("relative space-y-4 border-l border-line pl-5", className)}>
      {children}
    </ol>
  );
}

export function TimelineItem({
  title,
  timestamp,
  tone = "neutral",
  description,
  meta,
  children,
}: {
  title: ReactNode;
  /**
   * Already-formatted timestamp; formatting stays with the caller so the locale/UTC
   * choice is explicit. Rendered as a `<span>`, not a `<time>`: a locale
   * string is not a valid machine-readable `datetime`, and a `<time>` whose value
   * disagrees with its text is worse than no `<time>` at all.
   */
  timestamp?: ReactNode;
  tone?: Tone;
  description?: ReactNode;
  /** Identifier row: trace id, memory id, actor. */
  meta?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <li className="relative">
      <span
        aria-hidden
        className={cn(
          "absolute -left-[1.4375rem] top-1.5 h-2 w-2 rounded-full ring-4 ring-canvas",
          DOT_TONES[tone],
        )}
      />
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-sm font-medium text-fg">{title}</span>
          {timestamp ? (
            <span className="text-xs text-fg-muted">{timestamp}</span>
          ) : null}
        </div>
        {description ? (
          <p className="text-sm leading-relaxed text-fg-secondary">{description}</p>
        ) : null}
        {meta ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">{meta}</div>
        ) : null}
        {children}
      </div>
    </li>
  );
}
