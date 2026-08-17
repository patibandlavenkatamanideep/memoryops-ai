import type { ReactNode } from "react";

import { cn } from "./cn";

/**
 * Page and section headings.
 *
 * These exist to keep the document outline correct as much as to keep the type scale
 * consistent: every page gets exactly one `<h1>` from `PageHeader`, and section
 * titles are `<h2>`, so headings can actually be used to navigate the control plane
 * with a screen reader.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: {
  /** Short plane/domain label above the title, e.g. "Governance". */
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex flex-wrap items-end justify-between gap-4 border-b border-line pb-5",
        className,
      )}
    >
      <div className="min-w-0 space-y-1.5">
        {eyebrow ? (
          <p className="text-label uppercase text-fg-muted">{eyebrow}</p>
        ) : null}
        <h1 className="text-xl font-semibold tracking-tight text-fg sm:text-2xl">
          {title}
        </h1>
        {description ? (
          <p className="max-w-3xl text-sm leading-relaxed text-fg-secondary">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      ) : null}
    </header>
  );
}

export function SectionHeader({
  title,
  description,
  count,
  actions,
  className,
}: {
  title: string;
  description?: ReactNode;
  /** Rendered next to the title, e.g. "12 pending". Real counts only. */
  count?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-3", className)}>
      <div className="min-w-0 space-y-1">
        <h2 className="flex flex-wrap items-baseline gap-2 text-sm font-semibold text-fg">
          {title}
          {count !== undefined && count !== null ? (
            <span className="text-xs font-normal text-fg-muted">{count}</span>
          ) : null}
        </h2>
        {description ? (
          <p className="max-w-3xl text-xs leading-relaxed text-fg-secondary">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/** Small uppercase label above a group of values. Not a heading — no outline entry. */
export function FieldLabel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <p className={cn("text-label uppercase text-fg-muted", className)}>{children}</p>
  );
}
