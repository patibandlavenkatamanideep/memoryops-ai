/**
 * The web's UI personas.
 *
 * A list, not a ladder. The ordinal ranking that used to live here made
 * `memory_admin` outrank `auditor` — implying that managing memory grants access to
 * the evidence of who managed it, which the API has never allowed — and made `owner`
 * outrank everything, including deployment surfaces no tenant role can reach.
 *
 * Personas are translated to API roles by `contracts/auth-role-map.json`; what each
 * may attempt comes from `lib/capabilities.ts`, generated from the API's own
 * authorization objects. Nothing here implies precedence.
 */

export const ROLES = ["viewer", "developer", "auditor", "memory_admin", "owner"] as const;

export type Role = (typeof ROLES)[number];

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && (ROLES as readonly string[]).includes(value);
}
