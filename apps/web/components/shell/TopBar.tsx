"use client";

import { Badge } from "@/components/ui";
import type { ShellIdentity } from "./types";
import { activeNavItem } from "./navigation";

/**
 * Top bar: where you are, who you are, and (below `lg`) how to open the nav.
 *
 * The identity chip is display-only. It renders the scope the server already resolved
 * for this session — it is not a tenant switcher and nothing here is read back as
 * input, because scope is decided in lib/identity.ts and attached by the BFF, never
 * chosen by the browser.
 */
export default function TopBar({
  pathname,
  identity,
  navOpen,
  onToggleNav,
}: {
  pathname: string;
  identity: ShellIdentity | null;
  navOpen: boolean;
  onToggleNav: () => void;
}) {
  const current = activeNavItem(pathname);

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-canvas/90 px-4 backdrop-blur supports-[backdrop-filter]:bg-canvas/75 sm:px-6">
      <button
        type="button"
        onClick={onToggleNav}
        aria-expanded={navOpen}
        aria-controls="control-plane-nav"
        className="-ml-1 grid h-9 w-9 shrink-0 place-items-center rounded-md border border-line-strong text-fg-secondary hover:bg-surface-raised hover:text-fg lg:hidden"
      >
        <span className="sr-only">{navOpen ? "Close navigation" : "Open navigation"}</span>
        <svg
          aria-hidden
          viewBox="0 0 16 16"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          strokeLinecap="round"
        >
          {navOpen ? (
            <path d="M4 4l8 8M12 4l-8 8" />
          ) : (
            <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" />
          )}
        </svg>
      </button>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-fg">
          {current?.label ?? "MemoryOps"}
        </p>
      </div>

      {identity ? (
        <div className="flex min-w-0 items-center gap-2">
          <Badge tone={identity.isDemo ? "warn" : "neutral"} mono className="hidden sm:inline-flex">
            <span className="truncate" title={`${identity.tenantId} · ${identity.userId}`}>
              {identity.tenantId}/{identity.userId}
            </span>
          </Badge>
          <Badge tone="accent" className="shrink-0">
            {identity.role}
          </Badge>
        </div>
      ) : null}
    </header>
  );
}
