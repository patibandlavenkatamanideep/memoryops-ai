import type { ButtonHTMLAttributes } from "react";

import { cn } from "./cn";

/**
 * The control-plane button.
 *
 * `danger` is a distinct variant rather than a red `className`, because destructive
 * lifecycle actions (delete, reject) must look different from every other control at
 * a glance — a soft-delete is an audited, governed state change, not an undo-able
 * form action.
 *
 * `subtle` replaces the ad-hoc `<button className="text-rose-400 hover:underline">`
 * links that row actions used: those read as text, so nothing indicated they were
 * interactive until hover, and they carried no disabled or focus treatment.
 */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
export type ButtonSize = "sm" | "md";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-canvas font-medium hover:bg-accent-strong",
  secondary:
    "border border-line-strong bg-surface-raised text-fg hover:bg-surface-hover",
  ghost: "text-fg-secondary hover:bg-surface-raised hover:text-fg",
  danger: "border border-danger/40 bg-danger/10 text-danger hover:bg-danger/20",
  subtle: "text-fg-secondary underline-offset-4 hover:text-fg hover:underline",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-9 px-4 text-sm",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({
  variant = "secondary",
  size = "md",
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      // Buttons inside a <form> default to submit, which silently turned filter and
      // action controls into form submissions. Explicit unless the caller says so.
      type={type}
      className={cn(
        "inline-flex shrink-0 items-center justify-center gap-2 rounded-lg",
        "transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        // `subtle` is a text affordance; forcing it to button height misaligns it
        // inside table cells and inline rows.
        variant === "subtle" ? "text-xs" : SIZES[size],
        className,
      )}
      {...rest}
    />
  );
}
