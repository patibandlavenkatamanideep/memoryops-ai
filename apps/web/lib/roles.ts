/**
 * Role model and path→role policy.
 *
 * Deliberately free of `server-only`, NextAuth, and any Next.js runtime import, so
 * the authorization rules can be unit-tested directly. `lib/identity.ts` re-exports
 * these alongside the session-bound pieces.
 *
 * This is defence in depth layered on the API's own governance: it only ever
 * *removes* access. The API stays authoritative for every governance decision.
 */

/** Roles, least privilege first. */
export const ROLES = [
  "viewer", // read-only operator
  "developer", // application developer: read + chat
  "auditor", // read + audit/evidence surfaces
  "memory_admin", // memory lifecycle mutations (edit/delete/pin)
  "owner", // organisation owner: everything
] as const;

export type Role = (typeof ROLES)[number];

const ROLE_RANK: Record<Role, number> = {
  viewer: 0,
  developer: 1,
  auditor: 2,
  memory_admin: 3,
  owner: 4,
};

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && (ROLES as readonly string[]).includes(value);
}

export function hasAtLeast(role: Role, required: Role): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[required];
}

/**
 * Minimum role for a MemoryOps API path + method.
 *
 * Read paths are open to any authenticated role; mutations and evidence surfaces
 * are gated. Unknown paths default to the *least* privileged role so a newly added
 * endpoint is readable rather than accidentally wide open to mutation.
 */
export function requiredRole(path: string, method: string): Role {
  const p = path.startsWith("/") ? path : `/${path}`;
  const write = method !== "GET" && method !== "HEAD";

  // Running evals is cost-bearing (denial-of-wallet), so owner only.
  if (p.startsWith("/api/evals")) return "owner";
  // Retention, legal hold, consent withdrawal: governance mutations.
  if (p.startsWith("/api/retention")) return write ? "owner" : "auditor";
  // Audit trail + evidence reports.
  if (p.startsWith("/api/audit") || p.startsWith("/api/evidence")) return "auditor";
  // Memory lifecycle mutations need admin; reads do not.
  if (p.startsWith("/api/memories")) return write ? "memory_admin" : "viewer";
  // Chat writes memory, so it is not a read-only operation.
  if (p.startsWith("/api/chat")) return "developer";
  return "viewer";
}
