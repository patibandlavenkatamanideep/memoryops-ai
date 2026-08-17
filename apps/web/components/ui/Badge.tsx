import type { ReactNode } from "react";

import { cn } from "./cn";

/**
 * Status vocabulary for the control plane.
 *
 * Tone is chosen from *meaning*, never from taste, and the lifecycle mappings below
 * are the single place that decision is made. `deleted` in particular must never be
 * able to render as an active-looking state anywhere in the UI (invariant #2), which
 * is only guaranteeable if one map owns it.
 */
export type Tone = "neutral" | "accent" | "ok" | "warn" | "danger" | "info" | "quiet";

const TONES: Record<Tone, string> = {
  neutral: "border-line-strong bg-surface-raised text-fg-secondary",
  accent: "border-accent/40 bg-accent/10 text-accent-strong",
  ok: "border-ok/35 bg-ok/10 text-ok",
  warn: "border-warn/35 bg-warn/10 text-warn",
  danger: "border-danger/40 bg-danger/10 text-danger",
  info: "border-info/35 bg-info/10 text-info",
  quiet: "border-line bg-transparent text-fg-muted",
};

export function Badge({
  children,
  tone = "neutral",
  className,
  title,
  mono = false,
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
  title?: string;
  /** For ids, trace fragments and enum-shaped values. */
  mono?: boolean;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 truncate rounded-full border px-2 py-0.5 text-xs",
        mono && "font-mono text-[11px]",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/**
 * Memory lifecycle status → tone.
 *
 * Unknown statuses fall through to `neutral` rather than to a success tone: a state
 * this UI has not been taught about must not be presented as healthy.
 */
export const MEMORY_STATUS_TONE: Record<string, Tone> = {
  active: "ok",
  pending: "warn",
  archived: "neutral",
  rejected: "danger",
  blocked: "danger",
  deleted: "quiet",
};

/** Loop / worker run status → tone. */
export const RUN_STATUS_TONE: Record<string, Tone> = {
  completed: "ok",
  succeeded: "ok",
  running: "info",
  started: "info",
  safe_degraded: "warn",
  degraded: "warn",
  pending: "warn",
  failed: "danger",
  dead_letter: "danger",
};

export function toneForMemoryStatus(status: string): Tone {
  return MEMORY_STATUS_TONE[status] ?? "neutral";
}

export function toneForRunStatus(status: string): Tone {
  return RUN_STATUS_TONE[status] ?? "neutral";
}

export function StatusBadge({
  status,
  tone,
  className,
}: {
  status: string;
  /** Override when the status string is not a memory lifecycle state. */
  tone?: Tone;
  className?: string;
}) {
  const resolved = tone ?? toneForMemoryStatus(status);
  return (
    <Badge
      tone={resolved}
      // A deleted memory is struck through as well as de-toned. Colour alone is not a
      // sufficient signal — it is invisible to a colour-blind operator and to anyone
      // reading a greyscale screenshot in an incident review.
      className={cn(status === "deleted" && "line-through", className)}
    >
      {status}
    </Badge>
  );
}
