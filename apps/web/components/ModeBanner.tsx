import { resolveIdentity, webMode } from "@/lib/identity";

/**
 * Makes the operating mode unmissable.
 *
 * In demo mode the app runs on a shared `tenant_demo` identity with ephemeral data.
 * That was previously indistinguishable from a real deployment — the same UI, no
 * signal anywhere — so a demo could be mistaken for the production control plane.
 * Server component: it reads the server-only mode, never a client-spoofable value.
 */
export default async function ModeBanner() {
  if (webMode() !== "demo") return null;

  const identity = await resolveIdentity();

  return (
    <div
      role="status"
      className="border-b border-amber-300 bg-amber-50 px-6 py-2 text-sm text-amber-900"
    >
      <span className="font-semibold">Demo mode</span> — shared{" "}
      <code className="rounded bg-amber-100 px-1">{identity.tenantId}</code> workspace
      with ephemeral data and no authentication. Not the production control plane.{" "}
      <span className="opacity-80">
        Set <code>MEMORYOPS_WEB_MODE=authenticated</code> for the real thing.
      </span>
    </div>
  );
}
