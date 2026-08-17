import type { ReactNode } from "react";

import { cn } from "./cn";
import { Panel, PanelBody, PanelHeader } from "./Panel";

/**
 * Detail and evidence surfaces.
 *
 * A record's detail view is a panel with a header, a stack of sections, and an
 * evidence block for the raw governed values — the same shape for a memory, a loop
 * run and an audit event, so an operator learns the layout once.
 */
export function DetailPanel({
  title,
  description,
  actions,
  children,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Panel className={cn("overflow-hidden", className)}>
      <PanelHeader title={title} description={description} actions={actions} />
      <PanelBody className="space-y-5">{children}</PanelBody>
    </Panel>
  );
}

/**
 * Collapsible section built on native `<details>`.
 *
 * No state, no JS, no `aria-expanded` to keep in sync — the browser already gives
 * this correct keyboard operation and screen-reader semantics, and it works before
 * hydration. A hand-rolled toggle would only be worse.
 */
export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  className,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  return (
    <details
      open={defaultOpen}
      className={cn("group rounded-lg border border-line bg-surface-raised", className)}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-fg-secondary hover:text-fg">
        <span
          aria-hidden
          className="text-fg-muted transition-transform group-open:rotate-90"
        >
          ▸
        </span>
        {summary}
      </summary>
      <div className="border-t border-line px-3 py-3">{children}</div>
    </details>
  );
}

/**
 * Raw evidence rendering: structured values exactly as the API returned them.
 *
 * Pretty-printed and scrollable rather than summarised, because the point of an
 * evidence surface is that the operator sees the record, not this UI's reading of it.
 * Rendering is defensive — a value that cannot be serialised is reported as such
 * rather than throwing and taking the page down with it.
 */
export function EvidenceBlock({
  value,
  className,
  label,
}: {
  value: unknown;
  className?: string;
  label?: string;
}) {
  let text: string;
  try {
    text = JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    text = "// value could not be serialised for display";
  }
  return (
    <pre
      role="region"
      aria-label={label ?? "Evidence detail"}
      tabIndex={0}
      className={cn(
        "max-h-72 overflow-auto rounded-lg border border-line bg-surface-sunken p-3",
        "font-mono text-[11px] leading-relaxed text-fg-secondary",
        className,
      )}
    >
      {text}
    </pre>
  );
}
