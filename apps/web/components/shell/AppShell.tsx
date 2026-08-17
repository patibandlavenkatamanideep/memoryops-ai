"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import SidebarNav from "./SidebarNav";
import TopBar from "./TopBar";
import type { ShellIdentity } from "./types";
import { isChromeless } from "./navigation";

/**
 * The application shell: fixed sidebar on desktop, off-canvas drawer below `lg`.
 *
 * This is a client component because the shell has to know the current path (to mark
 * the active section) and hold drawer state. The pieces that must stay on the server
 * — the mode banner and identity resolution — are rendered there and passed in, so no
 * session lookup or server-only module is pulled across the boundary.
 *
 * It decides layout only. It does not gate any route: `/signin` renders without
 * chrome purely because a nav rail of links you cannot open yet is noise, and hiding
 * chrome is not access control. Route protection lives in middleware.ts and the BFF.
 */
export default function AppShell({
  children,
  banner,
  identity,
}: {
  children: ReactNode;
  /** Server-rendered mode banner, or null. */
  banner?: ReactNode;
  identity: ShellIdentity | null;
}) {
  const pathname = usePathname() ?? "/";
  const [navOpen, setNavOpen] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);

  const closeNav = useCallback(() => setNavOpen(false), []);

  // Navigating with the drawer open must not leave it covering the page it just
  // loaded. Keyed on the path so it also fires for links inside the content.
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  // Escape closes the drawer — the expected exit from any overlay, and the only one
  // available to a keyboard user who cannot click the backdrop.
  useEffect(() => {
    if (!navOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setNavOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [navOpen]);

  // Move focus into the drawer when it opens so the next Tab lands on a nav link
  // rather than continuing through the page behind it.
  useEffect(() => {
    if (navOpen) drawerRef.current?.focus();
  }, [navOpen]);

  // Stop the page behind the overlay from scrolling with it.
  useEffect(() => {
    if (!navOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [navOpen]);

  if (isChromeless(pathname)) {
    return (
      <>
        {banner}
        <main id="main-content" className="min-h-screen">
          {children}
        </main>
      </>
    );
  }

  return (
    <div className="min-h-screen">
      {banner}

      {/* First focusable element on the page: a keyboard user must be able to reach
          the content without tabbing the whole nav on every navigation. */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:border focus:border-accent focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:text-fg"
      >
        Skip to content
      </a>

      <div className="lg:flex">
        <aside className="hidden w-64 shrink-0 border-r border-line bg-surface lg:sticky lg:top-0 lg:block lg:h-screen">
          <SidebarNav pathname={pathname} footer={<ShellFooter identity={identity} />} />
        </aside>

        {navOpen ? (
          <>
            <div
              // Decorative scrim. The drawer itself is the dialog; this only dismisses
              // it, and Escape does the same for anyone not using a pointer.
              aria-hidden
              onClick={closeNav}
              className="fixed inset-0 z-40 bg-canvas/80 backdrop-blur-sm lg:hidden"
            />
            <div
              id="control-plane-nav"
              ref={drawerRef}
              role="dialog"
              aria-modal="true"
              aria-label="Control plane navigation"
              tabIndex={-1}
              // focus-visible:ring-0 suppresses the global focus ring on the panel
              // itself: focus is moved here programmatically to seed tab order, and a
              // ring around the whole drawer would read as "the drawer is the control".
              className="fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] border-r border-line bg-surface shadow-overlay focus-visible:ring-0 lg:hidden"
            >
              <SidebarNav
                pathname={pathname}
                onNavigate={closeNav}
                footer={<ShellFooter identity={identity} />}
              />
            </div>
          </>
        ) : null}

        <div className="min-w-0 flex-1">
          <TopBar
            pathname={pathname}
            identity={identity}
            navOpen={navOpen}
            onToggleNav={() => setNavOpen((open) => !open)}
          />
          <main id="main-content" className="px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
            <div className="mx-auto max-w-[90rem] space-y-6">{children}</div>
          </main>
        </div>
      </div>
    </div>
  );
}

/**
 * Sidebar footer: the operating scope, stated where it cannot be missed.
 *
 * A control plane that governs tenant-isolated memory should never leave "which
 * tenant am I acting on" to be inferred from the data on screen.
 */
function ShellFooter({ identity }: { identity: ShellIdentity | null }) {
  if (!identity) {
    return <p className="text-xs text-fg-muted">Not signed in</p>;
  }
  return (
    <div className="space-y-1">
      <p className="text-label uppercase text-fg-muted">Operating scope</p>
      <p className="truncate font-mono text-xs text-fg-secondary" title={identity.tenantId}>
        {identity.tenantId}
      </p>
      <p className="truncate font-mono text-xs text-fg-muted" title={identity.userId}>
        {identity.userId}
      </p>
    </div>
  );
}
