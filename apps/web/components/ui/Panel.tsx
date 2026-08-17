import type { ReactNode } from "react";

import { cn } from "./cn";

/**
 * The one container primitive.
 *
 * `tone` exists so a panel can carry a governance meaning — a blocked decision, a
 * legal hold — without every caller inventing its own border colour. It is never
 * used decoratively.
 */
export type PanelTone = "default" | "accent" | "ok" | "warn" | "danger";

const TONES: Record<PanelTone, string> = {
  default: "border-line",
  accent: "border-accent/40",
  ok: "border-ok/35",
  warn: "border-warn/35",
  danger: "border-danger/40",
};

export function Panel({
  children,
  className,
  tone = "default",
  as: Tag = "section",
}: {
  children: ReactNode;
  className?: string;
  tone?: PanelTone;
  as?: "section" | "article" | "div" | "aside";
}) {
  return (
    <Tag className={cn("rounded-panel border bg-surface", TONES[tone], className)}>
      {children}
    </Tag>
  );
}

/** Header strip inside a panel. Separated by a rule, not by whitespace alone. */
export function PanelHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3",
        className,
      )}
    >
      <div className="min-w-0 space-y-1">
        <h2 className="text-sm font-semibold text-fg">{title}</h2>
        {description ? (
          <p className="text-xs text-fg-secondary">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function PanelBody({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn("p-4", className)}>{children}</div>;
}

export function PanelFooter({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("border-t border-line px-4 py-3 text-xs text-fg-muted", className)}>
      {children}
    </div>
  );
}
