import type { Metadata } from "next";
import "./globals.css";
import AppShell from "@/components/shell/AppShell";
import type { ShellIdentity } from "@/components/shell/types";
import ModeBanner from "@/components/ModeBanner";
import { resolveIdentity, UnauthenticatedError } from "@/lib/identity";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "MemoryOps AI — Govern what AI remembers",
  description:
    "A governed memory lifecycle for AI assistants: capture, evaluate, store, retrieve, rank, compose, update, forget, audit.",
};

/**
 * The caller, projected for the shell's identity chip.
 *
 * Only `UnauthenticatedError` degrades to `null` — that is the expected state on
 * `/signin` and for anyone middleware is about to redirect. Every other error
 * propagates: `webMode()` throws when `MEMORYOPS_WEB_MODE` is unset in production,
 * and swallowing that would turn a deliberate fail-closed configuration guard into a
 * page that renders as though nobody were signed in.
 */
async function shellIdentity(): Promise<ShellIdentity | null> {
  try {
    const identity = await resolveIdentity();
    return {
      tenantId: identity.tenantId,
      userId: identity.userId,
      role: identity.role,
      isDemo: identity.isDemo,
    };
  } catch (error) {
    if (error instanceof UnauthenticatedError) return null;
    throw error;
  }
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const identity = await shellIdentity();

  return (
    <html lang="en">
      <body>
        {/* ModeBanner stays a server component; the shell receives it as an element
            rather than importing it, so no server-only module crosses the boundary. */}
        <AppShell banner={<ModeBanner />} identity={identity}>
          {children}
        </AppShell>
      </body>
    </html>
  );
}
