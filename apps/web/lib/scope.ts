/**
 * Scope sanitisation for the BFF proxy — the security boundary of the web app.
 *
 * The browser must never be able to choose which tenant/user it addresses. Before
 * the BFF inserts the server-resolved identity, it removes any `tenant_id` /
 * `user_id` the client supplied, from both the query string and the JSON body.
 *
 * This lives in its own module (rather than inside the route handler) because
 * Next.js route files may only export HTTP verbs and a fixed set of config fields —
 * an extra export there is a build error. Keeping it here means the rules are
 * directly unit-testable, which for a boundary this load-bearing matters more than
 * the extra file.
 */

/** Scope keys the client is never allowed to influence. */
export const SCOPE_KEYS = ["tenant_id", "user_id"] as const;

/** Remove client-supplied scope from a query string. Mutates and returns `params`. */
export function stripClientScope(params: URLSearchParams): URLSearchParams {
  for (const key of SCOPE_KEYS) params.delete(key);
  return params;
}

/** Remove client-supplied scope from a parsed JSON body. Returns a copy. */
export function stripScopeFromBody(body: unknown): unknown {
  if (!body || typeof body !== "object" || Array.isArray(body)) return body;
  const clone: Record<string, unknown> = { ...(body as Record<string, unknown>) };
  for (const key of SCOPE_KEYS) delete clone[key];
  return clone;
}
