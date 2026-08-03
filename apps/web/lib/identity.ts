import "server-only";

/**
 * Server-side identity resolution for the MemoryOps control plane.
 *
 * Why this exists
 * ---------------
 * `lib/api.ts` used to export hardcoded constants:
 *
 *     export const DEMO_TENANT = "tenant_demo";
 *     export const DEMO_USER   = "user_demo";
 *
 * and put them in the query string or body of every request, straight from the
 * browser. Two consequences:
 *
 *  1. There was no identity at all — every visitor was the same tenant/user.
 *  2. Because the scope travelled in client-controlled request data, anyone could
 *     edit it in devtools and address another tenant. The API's own scope
 *     validation is what stopped that, but only when `MEMORYOPS_AUTH_MODE` is set;
 *     the shipped web app sent no credential at all, so it could only ever work
 *     against `auth_mode=none` — which the production profile refuses to run.
 *     The official UI and the production security profile were mutually exclusive.
 *
 * Identity is now resolved **only here, on the server**, and is never accepted from
 * the client. The BFF proxy (`app/api/memoryops/[...path]/route.ts`) strips any
 * client-supplied `tenant_id`/`user_id` and substitutes what this module returns.
 */

import { auth } from "@/auth";
import { isRole, type Role } from "@/lib/roles";

// Re-exported so callers have one import site; the rules themselves live in
// lib/roles.ts, free of server-only/NextAuth so they stay directly unit-testable.
export { hasAtLeast, isRole, requiredRole, ROLES } from "@/lib/roles";
export type { Role } from "@/lib/roles";

export type WebMode = "demo" | "authenticated";

export interface Identity {
  tenantId: string;
  userId: string;
  role: Role;
  /** True when this identity came from the demo fallback rather than a session. */
  isDemo: boolean;
}

/**
 * `MEMORYOPS_WEB_MODE` is deliberately **not** `NEXT_PUBLIC_*`: authorization must
 * never be decided by a value the browser bundle can read or a client can spoof.
 * `NEXT_PUBLIC_MEMORYOPS_WEB_MODE` exists separately for cosmetics only (the demo
 * banner) and is never consulted for access decisions.
 */
export function webMode(): WebMode {
  const configured = process.env.MEMORYOPS_WEB_MODE;
  if (configured === "demo" || configured === "authenticated") return configured;

  // Defaulting to `demo` is right for local development and wrong for a deployed
  // build: an unset variable would silently serve the shared `tenant_demo` persona
  // as though that were intended. Production must say which mode it means.
  //
  // `next build` runs with NODE_ENV=production and prerenders pages, so throwing on
  // NODE_ENV alone breaks the image build for a value that is only meaningful at
  // request time. NEXT_PHASE distinguishes the two: during the build we fall back
  // so prerendering can complete, and the deployed server still refuses to serve a
  // request without an explicit mode.
  const isBuildPhase = process.env.NEXT_PHASE === "phase-production-build";
  if (process.env.NODE_ENV === "production" && !isBuildPhase) {
    throw new Error(
      "MEMORYOPS_WEB_MODE must be explicitly set to 'demo' or 'authenticated' in production",
    );
  }
  return "demo";
}

export const DEMO_IDENTITY: Identity = {
  tenantId: "tenant_demo",
  userId: "user_demo",
  role: "owner",
  isDemo: true,
};

export class UnauthenticatedError extends Error {
  constructor() {
    super("no authenticated session");
    this.name = "UnauthenticatedError";
  }
}

/**
 * The single source of truth for who the caller is.
 *
 * - demo mode: the shared demo identity, clearly labelled as such.
 * - authenticated mode: derived from the Auth.js session; throws when absent.
 *   It never falls back to the demo identity — a broken session must fail closed,
 *   not silently hand the caller a working tenant.
 */
export async function resolveIdentity(): Promise<Identity> {
  if (webMode() === "demo") return DEMO_IDENTITY;

  const session = await auth();
  const user = session?.user as
    | { tenantId?: string; memoryopsUserId?: string; role?: string }
    | undefined;

  if (!user?.tenantId || !user?.memoryopsUserId) throw new UnauthenticatedError();

  return {
    tenantId: user.tenantId,
    userId: user.memoryopsUserId,
    // Unknown/absent role degrades to the least privileged one, never the most.
    role: isRole(user.role) ? user.role : "viewer",
    isDemo: false,
  };
}
