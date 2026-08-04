import type { Role as WebRole } from "./roles";
import {
  API_ROLES,
  NEVER_ASSIGNABLE_TO_HUMANS,
  WEB_TO_API_ROLE_MAP,
} from "./roleMap.generated";

/**
 * Translate a web persona into the API's authorization role.
 *
 * The web and the API have separate vocabularies on purpose — the web names
 * *personas* an operator picks, the API names *authorization bundles*. What was
 * missing was the translation between them.
 *
 * The BFF minted `identity.role` straight into the API credential, so:
 *
 *     viewer       -> API does not recognise it -> zero permissions
 *     developer    -> API does not recognise it -> zero permissions
 *     owner        -> API does not recognise it -> zero permissions
 *     auditor      -> recognised
 *     memory_admin -> recognised
 *
 * Three of the five human roles had no API access at all — including `owner`,
 * which the demo identity uses. Fail-closed, since an unrecognised role resolves to
 * zero permissions, but the authenticated web experience was broken.
 *
 * `contracts/auth-role-map.json` is the authoritative source for the *translation*
 * — not for the authorization model. The permission bundles live in the API's
 * `roles.py`; tests assert the contract and that vocabulary agree. Web tests check
 * every persona maps to something; API tests check every target is a role the API
 * recognises. Neither side can drift alone.
 *
 * The import below is a *generated* mirror of that contract
 * (`scripts/sync_role_contract.py`, drift-checked in CI). The web Dockerfile builds
 * with `apps/web` as its context, so a repo-root import is absent from the image —
 * the production build failed on exactly that.
 */

const WEB_TO_API: Record<string, string> = { ...WEB_TO_API_ROLE_MAP };

export type ApiRole = (typeof API_ROLES)[number];

export { API_ROLES, NEVER_ASSIGNABLE_TO_HUMANS };

export class UnmappedWebRoleError extends Error {
  constructor(role: string) {
    super(`no API role mapped for web role '${role}'`);
    this.name = "UnmappedWebRoleError";
  }
}

/**
 * Fail closed on an unknown persona rather than passing it through. Passing it
 * through is exactly how the original break happened: the API received a name it
 * did not recognise and the caller silently lost every permission.
 */
export function apiRoleForWebRole(role: WebRole | string): ApiRole {
  const mapped = WEB_TO_API[role];
  if (!mapped) throw new UnmappedWebRoleError(String(role));
  return mapped as ApiRole;
}

/** The full mapping, for tests and diagnostics. */
export const WEB_TO_API_ROLES: Readonly<Record<string, string>> = Object.freeze({
  ...WEB_TO_API,
});
