import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/components/ui";

/**
 * Chrome for the public product page.
 *
 * Separate from `AppShell` on purpose. The control-plane shell exists to tell an
 * operator which tenant they are acting on and to move them between governed
 * surfaces; a visitor who is not signed in has no tenant and cannot open any of
 * those links. Rendering them a sidebar of redirects-to-sign-in would be noise
 * dressed as navigation.
 *
 * It uses the same tokens and primitives as the control plane rather than a second
 * visual language — this is the same product, seen from outside.
 *
 * Deliberately a server component with no state: the header is a wordmark, two
 * in-page anchors and one call to action. Nothing here needs hydration, so the
 * public page ships no shell JavaScript at all.
 */

/** In-page anchors. Section ids are owned by the section components. */
const SECTION_LINKS = [
  { href: "#decision-trace", label: "How it works" },
  { href: "#lifecycle", label: "Lifecycle" },
  { href: "#capabilities", label: "Capabilities" },
] as const;

export function PublicShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:border focus:border-accent focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:text-fg"
      >
        Skip to content
      </a>
      <PublicHeader />
      <main id="main-content">{children}</main>
      <PublicFooter />
    </div>
  );
}

function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5 text-sm font-semibold tracking-tight text-fg", className)}>
      <span
        aria-hidden
        className="grid h-7 w-7 place-items-center rounded-md border border-accent/40 bg-accent/10 font-mono text-[11px] text-accent-strong"
      >
        MO
      </span>
      MemoryOps<span className="text-fg-muted"> AI</span>
    </span>
  );
}

function PublicHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-canvas/90 backdrop-blur supports-[backdrop-filter]:bg-canvas/75">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-5 sm:px-8">
        <Link href="/" className="inline-flex min-h-[2.5rem] shrink-0 items-center rounded-md">
          <Wordmark />
        </Link>

        {/* Hidden on small screens rather than collapsed into a drawer: three
            in-page anchors do not justify a toggle, and the page is short enough
            to scroll. The CTA stays visible at every width. */}
        <nav aria-label="Page sections" className="hidden flex-1 items-center gap-6 md:flex">
          {SECTION_LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="inline-flex min-h-[2rem] items-center rounded-sm text-sm text-fg-secondary transition-colors hover:text-fg"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3 md:ml-0">
          {/*
           * `/chat` rather than `/signin`, because it is correct in every mode:
           * authenticated + no session redirects to sign-in with a callback back
           * here, authenticated + session lands in the control plane, and demo mode
           * opens the demo directly. `/signin` would dead-end in demo mode, where it
           * redirects to `/` — a button that returns you to the page you clicked it
           * on.
           */}
          <Link
            href="/chat"
            className="inline-flex h-9 shrink-0 items-center justify-center rounded-lg bg-accent px-4 text-sm font-medium text-canvas transition-colors hover:bg-accent-strong"
          >
            Open control plane
          </Link>
        </div>
      </div>
    </header>
  );
}

function PublicFooter() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-5 py-10 sm:px-8 md:flex-row md:items-start md:justify-between">
        <div className="space-y-2">
          <Wordmark />
          <p className="max-w-sm text-xs leading-relaxed text-fg-muted">
            A governed memory lifecycle for AI assistants and agents: capture,
            evaluate, store, retrieve, rank, compose, update, forget, audit.
          </p>
        </div>
        <nav aria-label="Footer" className="flex flex-col gap-2 text-sm">
          <Link
            href="/chat"
            className="inline-flex min-h-[2rem] items-center rounded-sm text-fg-secondary underline-offset-4 hover:text-fg hover:underline"
          >
            Open control plane
          </Link>
          <Link
            href="/architecture"
            className="inline-flex min-h-[2rem] items-center rounded-sm text-fg-secondary underline-offset-4 hover:text-fg hover:underline"
          >
            Technical architecture reference
          </Link>
        </nav>
      </div>
    </footer>
  );
}

/** Shared section wrapper: consistent rhythm and a single max width. */
export function Section({
  id,
  children,
  className,
  bordered = true,
}: {
  id?: string;
  children: ReactNode;
  className?: string;
  bordered?: boolean;
}) {
  return (
    <section
      id={id}
      // scroll-mt clears the sticky header when an anchor link jumps here.
      className={cn(
        "scroll-mt-20 px-5 py-16 sm:px-8 sm:py-20",
        bordered && "border-t border-line",
        className,
      )}
    >
      <div className="mx-auto max-w-6xl">{children}</div>
    </section>
  );
}

/** Section heading block. `<h2>` so the page keeps one `<h1>` in the hero. */
export function SectionIntro({
  eyebrow,
  title,
  children,
  aside,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="mb-10 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl space-y-3">
        <p className="text-label uppercase text-accent-strong">{eyebrow}</p>
        <h2 className="text-2xl font-semibold tracking-tight text-fg sm:text-3xl">
          {title}
        </h2>
        {children ? (
          <p className="text-base leading-relaxed text-fg-secondary">{children}</p>
        ) : null}
      </div>
      {aside ? <div className="shrink-0">{aside}</div> : null}
    </div>
  );
}
