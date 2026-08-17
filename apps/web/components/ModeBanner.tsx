import { Code } from "@/components/ui";
import { resolveIdentity, webMode } from "@/lib/identity";

/**
 * Makes the operating mode unmissable.
 *
 * In demo mode the app runs on a shared `tenant_demo` identity with ephemeral data.
 * That was previously indistinguishable from a real deployment — the same UI, no
 * signal anywhere — so a demo could be mistaken for the production control plane.
 * Server component: it reads the server-only mode, never a client-spoofable value.
 *
 * It sits above the shell rather than inside a page so it cannot be scrolled away
 * from or forgotten on a surface that did not opt in.
 */
export default async function ModeBanner() {
  if (webMode() !== "demo") return null;

  const identity = await resolveIdentity();

  return (
    <div
      role="status"
      className="border-b border-warn/30 bg-warn/10 px-4 py-2 text-xs text-warn sm:px-6"
    >
      <span className="font-semibold">Demo mode</span>{" "}
      <span className="text-fg-secondary">
        — shared <Code className="text-warn">{identity.tenantId}</Code> workspace with
        ephemeral data and no authentication. Not the production control plane. Set{" "}
        <Code className="text-fg-secondary">MEMORYOPS_WEB_MODE=authenticated</Code> for
        the real thing.
      </span>
    </div>
  );
}
