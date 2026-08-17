import type { ReactNode } from "react";

import { cn } from "./cn";

/**
 * Empty / loading / error are first-class states, not afterthoughts.
 *
 * The control plane renders real tenant data, and a new tenant's tables are legitimately
 * empty. Padding those screens with sample rows would make fabricated data
 * indistinguishable from governed state, so an empty dataset gets an explanation of
 * *why* it is empty and what fills it instead.
 */
export function EmptyState({
  title,
  description,
  action,
  className,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-panel border border-dashed",
        "border-line-strong bg-surface/40 px-6 py-10 text-center",
        className,
      )}
    >
      <p className="text-sm font-medium text-fg-secondary">{title}</p>
      {description ? (
        <p className="max-w-md text-xs leading-relaxed text-fg-muted">{description}</p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

/**
 * Loading is announced, not just animated: `role="status"` + `aria-live="polite"` so a
 * screen reader learns the view is fetching. The bars are decorative and hidden.
 */
export function LoadingState({
  label = "Loading…",
  rows = 3,
  className,
}: {
  label?: string;
  rows?: number;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn("space-y-2 rounded-panel border border-line bg-surface p-4", className)}
    >
      <span className="sr-only">{label}</span>
      <span aria-hidden className="block text-xs text-fg-muted">
        {label}
      </span>
      {Array.from({ length: rows }).map((_, i) => (
        <span
          key={i}
          aria-hidden
          className="block h-3 animate-mo-pulse rounded bg-surface-hover"
          style={{ width: `${100 - i * 12}%` }}
        />
      ))}
    </div>
  );
}

/** Inline skeleton for a single value that is still resolving. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block h-4 w-16 animate-mo-pulse rounded bg-surface-hover", className)}
    />
  );
}

/**
 * Errors carry `role="alert"` so failure is announced rather than silently rendered in
 * red — and red-only was the previous signal, which is not perceivable to every
 * operator.
 */
export function ErrorState({
  title = "Request failed",
  detail,
  action,
  className,
}: {
  title?: string;
  detail?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-wrap items-start justify-between gap-3 rounded-panel border border-danger/40",
        "bg-danger/10 px-4 py-3",
        className,
      )}
    >
      <div className="min-w-0 space-y-1">
        <p className="text-sm font-medium text-danger">{title}</p>
        {detail ? (
          <p className="break-words font-mono text-xs text-fg-secondary">{detail}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
