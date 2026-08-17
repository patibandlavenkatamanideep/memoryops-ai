"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/components/ui";
import NavIcon from "./NavIcon";
import { NAV_GROUPS, isActivePath } from "./navigation";

/**
 * The control-plane sidebar.
 *
 * One component serves both the fixed desktop rail and the mobile drawer, so the two
 * cannot drift apart in what they list. The parent decides placement; this decides
 * content and state.
 *
 * The active link carries `aria-current="page"` as well as its colour and rule, so
 * "where am I" is answerable without seeing the styling.
 */
export default function SidebarNav({
  pathname,
  onNavigate,
  footer,
}: {
  pathname: string;
  /** Called when a link is followed — the drawer uses it to close itself. */
  onNavigate?: () => void;
  footer?: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line px-4 py-4">
        <Link
          href="/"
          onClick={onNavigate}
          className="flex items-center gap-2.5 rounded-md text-sm font-semibold tracking-tight text-fg"
        >
          <span
            aria-hidden
            className="grid h-7 w-7 place-items-center rounded-md border border-accent/40 bg-accent/10 font-mono text-[11px] text-accent-strong"
          >
            MO
          </span>
          <span>
            MemoryOps<span className="text-fg-muted"> AI</span>
          </span>
        </Link>
        <p className="mt-2 text-label uppercase text-fg-muted">Memory control plane</p>
      </div>

      <nav aria-label="Control plane" className="flex-1 overflow-y-auto px-3 py-4">
        <ul className="space-y-6">
          {NAV_GROUPS.map((group) => (
            <li key={group.label}>
              <p className="px-2 pb-2 text-label uppercase text-fg-muted">
                {group.label}
              </p>
              <ul className="space-y-0.5">
                {group.items.map((item) => {
                  const active = isActivePath(pathname, item.href);
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        onClick={onNavigate}
                        aria-current={active ? "page" : undefined}
                        title={item.summary}
                        className={cn(
                          "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
                          active
                            ? "bg-accent/10 font-medium text-fg"
                            : "text-fg-secondary hover:bg-surface-raised hover:text-fg",
                        )}
                      >
                        <span className={active ? "text-accent-strong" : "text-fg-muted"}>
                          <NavIcon glyph={item.glyph} />
                        </span>
                        <span className="truncate">{item.label}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
      </nav>

      {footer ? <div className="border-t border-line px-4 py-3">{footer}</div> : null}
    </div>
  );
}
