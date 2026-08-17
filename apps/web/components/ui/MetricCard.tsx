import type { ReactNode } from "react";

import { cn } from "./cn";
import { Skeleton } from "./States";

/**
 * A single measured value.
 *
 * `value` accepts `null` for "not loaded yet" and renders a skeleton, distinct from a
 * real zero. The previous cards printed `?? 0`, so a failed or pending metrics fetch
 * was indistinguishable from a tenant that genuinely has none of that thing — the one
 * confusion an operations surface cannot afford.
 *
 * There is no trend/sparkline affordance here by design: the API returns point-in-time
 * counters, so a delta would have to be invented.
 */
export function MetricCard({
  label,
  value,
  hint,
  tone = "default",
  className,
}: {
  label: string;
  /** `null` renders "not yet known", never a zero. */
  value: ReactNode | null;
  hint?: ReactNode;
  tone?: "default" | "accent" | "ok" | "warn" | "danger";
  className?: string;
}) {
  const valueTone = {
    default: "text-fg",
    accent: "text-accent-strong",
    ok: "text-ok",
    warn: "text-warn",
    danger: "text-danger",
  }[tone];

  return (
    <div
      className={cn(
        "rounded-panel border border-line bg-surface px-4 py-3.5",
        className,
      )}
    >
      <p className="text-label uppercase text-fg-muted">{label}</p>
      <p className={cn("mt-1.5 truncate text-2xl font-semibold tracking-tight", valueTone)}>
        {value === null ? <Skeleton className="h-6 w-12 align-middle" /> : value}
      </p>
      {hint ? <p className="mt-1 text-xs leading-snug text-fg-muted">{hint}</p> : null}
    </div>
  );
}

/** Responsive grid for a row of metrics. Wraps rather than shrinking below legibility. */
export function MetricGrid({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
        className,
      )}
    >
      {children}
    </div>
  );
}
