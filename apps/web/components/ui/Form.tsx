import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

import { cn } from "./cn";

/**
 * Form controls.
 *
 * Every control here is labelled by *wrapping* it in its `<label>` rather than by
 * pairing `htmlFor` with a generated id. Implicit association cannot drift: there is
 * no id to forget, collide, or lose when a control is moved. It also keeps these
 * usable from server components, since nothing needs `useId`.
 *
 * Placeholder text is never the label — a placeholder disappears on input and is not
 * reliably announced, which is how the memory search box ended up with no accessible
 * name at all.
 */

const CONTROL = [
  "w-full rounded-lg border border-line-strong bg-surface-sunken px-3 py-2 text-sm",
  "text-fg transition-colors",
  "hover:border-line-strong focus:border-accent",
  "disabled:cursor-not-allowed disabled:opacity-50",
].join(" ");

export function Field({
  label,
  hint,
  children,
  className,
  labelClassName,
  /** Renders the label to assistive tech only, for controls whose purpose is visually obvious. */
  hideLabel = false,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
  labelClassName?: string;
  hideLabel?: boolean;
}) {
  return (
    <label className={cn("block space-y-1.5", className)}>
      <span
        className={cn(
          hideLabel ? "sr-only" : "block text-xs font-medium text-fg-secondary",
          labelClassName,
        )}
      >
        {label}
      </span>
      {children}
      {hint ? <span className="block text-xs text-fg-muted">{hint}</span> : null}
    </label>
  );
}

export function TextInput({
  className,
  ...rest
}: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(CONTROL, className)} {...rest} />;
}

export function TextArea({
  className,
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(CONTROL, "resize-y leading-relaxed", className)} {...rest} />;
}

export function Select({
  className,
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement> & { children: ReactNode }) {
  return (
    <select className={cn(CONTROL, "appearance-none pr-8", className)} {...rest}>
      {children}
    </select>
  );
}

/**
 * Checkbox with its text to the right.
 *
 * The whole row is the label, so the hit target is the text as well as the 16px box —
 * a checkbox alone is below every recommended touch-target size.
 */
export function Checkbox({
  label,
  className,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  return (
    <label
      className={cn(
        "inline-flex cursor-pointer select-none items-center gap-2 text-sm text-fg-secondary",
        className,
      )}
    >
      <input
        type="checkbox"
        className="h-4 w-4 shrink-0 rounded border-line-strong bg-surface-sunken accent-accent"
        {...rest}
      />
      <span>{label}</span>
    </label>
  );
}

/**
 * Filter / search bar.
 *
 * `role="search"` when it contains the view's primary query control, so it is
 * reachable as a landmark.
 */
export function Toolbar({
  children,
  className,
  search = false,
}: {
  children: ReactNode;
  className?: string;
  search?: boolean;
}) {
  return (
    <div
      role={search ? "search" : undefined}
      className={cn(
        "flex flex-wrap items-end gap-3 rounded-panel border border-line bg-surface p-3",
        className,
      )}
    >
      {children}
    </div>
  );
}
