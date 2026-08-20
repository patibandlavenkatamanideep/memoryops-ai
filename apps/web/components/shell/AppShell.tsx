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
  /** Whatever had focus when the drawer opened — almost always the toggle button. */
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  /**
   * Dismiss and hand focus back to whatever opened it.
   *
   * Restoring here rather than in an effect cleanup is deliberate: by the time a
   * cleanup runs the panel is already unmounted and focus has fallen to <body>, so
   * there is no longer any way to tell whether focus *was* inside the drawer. Doing
   * it at the point of dismissal keeps the decision unambiguous.
   */
  const closeNav = useCallback(() => {
    setNavOpen(false);
    const target = restoreFocusRef.current;
    if (target?.isConnected) {
      // After the commit that removes the drawer, or the browser drops the focus.
      requestAnimationFrame(() => target.focus());
    }
  }, []);

  /**
   * Dismiss because the user is navigating away.
   *
   * No focus restoration: the destination page decides where focus belongs, and
   * yanking it back to a hamburger button the user has just navigated away from
   * would be worse than leaving it at the document start.
   */
  const dismissForNavigation = useCallback(() => setNavOpen(false), []);

  // Navigating with the drawer open must not leave it covering the page it just
  // loaded. Keyed on the path so it also fires for links inside the content.
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  /**
   * Keyboard contract for the open drawer: Escape closes it, and Tab stays inside it.
   *
   * The trap is the load-bearing half. The panel already declares
   * `role="dialog" aria-modal="true"`, which tells assistive tech the background is
   * inert — but `aria-modal` moves no focus. Without this, tabbing past the last nav
   * link walked straight into the page underneath, which the scrim has covered: an
   * operator could focus and activate a Delete button they could not see.
   */
  useEffect(() => {
    if (!navOpen) return;

    function focusable(): HTMLElement[] {
      const root = drawerRef.current;
      if (!root) return [];
      return [
        ...root.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ].filter((el) => el.offsetParent !== null);
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        closeNav();
        return;
      }
      if (event.key !== "Tab") return;

      const items = focusable();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;

      // Wrap at both ends, and pull focus back in if it is somehow outside already.
      if (!drawerRef.current?.contains(active)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [navOpen, closeNav]);

  // Seed focus inside the drawer, and remember where to send it back to.
  useEffect(() => {
    if (!navOpen) return;
    restoreFocusRef.current = document.activeElement as HTMLElement | null;
    drawerRef.current?.focus();
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
    // A chromeless route supplies its own landmarks. Wrapping `children` in a
    // <main> here produced two nested <main> elements on `/` — one from this
    // branch and one from PublicShell — both carrying id="main-content", so the
    // document had a duplicate id and the skip link pointed at the outer wrapper
    // rather than the page content.
    return (
      <>
        {banner}
        {children}
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
                onNavigate={dismissForNavigation}
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
