// GENERATED FILE — DO NOT EDIT BY HAND.
//
// Source of truth: contracts/auth-role-map.json
// Regenerate:      python scripts/sync_role_contract.py
// Verify:          python scripts/sync_role_contract.py --check   (CI gate)
//
// Committed inside apps/web because the web Dockerfile builds with apps/web as its
// context, so a repo-root import is not present in the image.

export const WEB_TO_API_ROLE_MAP = {
  viewer: "memory_viewer",
  developer: "memory_user",
  auditor: "auditor",
  memory_admin: "memory_admin",
  owner: "tenant_admin",
} as const;

export const API_ROLES = [
  "memory_viewer",
  "memory_user",
  "auditor",
  "memory_admin",
  "tenant_admin",
  "service_worker",
  "platform_operator",
] as const;

export const NEVER_ASSIGNABLE_TO_HUMANS = [
  "service_worker",
] as const;

export const ROLE_CONTRACT_VERSION = 1;
