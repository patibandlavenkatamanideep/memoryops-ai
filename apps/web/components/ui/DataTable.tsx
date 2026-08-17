import type { ReactNode, ThHTMLAttributes, TdHTMLAttributes } from "react";

import { cn } from "./cn";

/**
 * Table shell for the control plane's dense record views.
 *
 * Composable rather than config-driven on purpose: every table here renders a
 * different governance shape (lifecycle actions, provenance, evidence links), and a
 * `columns={[…]}` API would have ended up with a `render` escape hatch on most of
 * them anyway.
 *
 * What it does own is the parts that were wrong everywhere:
 *
 *  - the horizontal-scroll container is a labelled, focusable region, so an operator
 *    on a narrow viewport can reach the overflowing columns with the keyboard instead
 *    of only by trackpad;
 *  - `<caption>` gives the table an accessible name (visually hidden);
 *  - column headers are real `<th scope="col">`.
 */
export function DataTable({
  caption,
  children,
  className,
}: {
  /** Accessible name for the table and its scroll region. Required, not optional. */
  caption: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      role="region"
      aria-label={caption}
      tabIndex={0}
      className={cn(
        "overflow-x-auto rounded-panel border border-line bg-surface",
        className,
      )}
    >
      <table className="w-full min-w-[40rem] border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return (
    <thead className="border-b border-line bg-surface-raised">
      <tr>{children}</tr>
    </thead>
  );
}

export function TH({
  children,
  className,
  ...rest
}: ThHTMLAttributes<HTMLTableCellElement> & { children: ReactNode }) {
  return (
    <th
      scope="col"
      className={cn(
        "whitespace-nowrap px-3 py-2 text-label font-medium uppercase text-fg-muted",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

export function TBody({ children }: { children: ReactNode }) {
  return <tbody>{children}</tbody>;
}

export function TR({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <tr
      className={cn(
        "border-b border-line align-top last:border-b-0 hover:bg-surface-raised/60",
        className,
      )}
    >
      {children}
    </tr>
  );
}

export function TD({
  children,
  className,
  ...rest
}: TdHTMLAttributes<HTMLTableCellElement> & { children: ReactNode }) {
  return (
    <td className={cn("px-3 py-2.5 text-fg-secondary", className)} {...rest}>
      {children}
    </td>
  );
}

/** Full-width row for the empty case, so the table keeps its header and shape. */
export function TableEmptyRow({
  colSpan,
  children,
}: {
  colSpan: number;
  children: ReactNode;
}) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-3 py-8 text-center text-sm text-fg-muted">
        {children}
      </td>
    </tr>
  );
}
