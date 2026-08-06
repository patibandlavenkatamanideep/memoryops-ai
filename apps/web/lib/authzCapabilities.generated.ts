// GENERATED FILE — DO NOT EDIT BY HAND.
//
// Source of truth: services/api/app/auth/{authz_spec,roles}.py
//                  contracts/auth-role-map.json
// Regenerate:      python scripts/generate_web_capabilities.py
// Verify:          python scripts/generate_web_capabilities.py --check   (CI gate)
//
// The web used to rank personas (viewer < developer < auditor < memory_admin <
// owner) and ask "is this role at least X". The API grants capabilities, and the two
// disagree: memory_admin outranks auditor on the ladder but holds no evidence
// permission at the API, and owner outranks everything but holds no ops:* permission
// at all. This mirrors what the server actually enforces, so the disagreement cannot
// return silently.
//
// Committed inside apps/web because the web Dockerfile builds with apps/web as its
// context, so a repo-root import is not present in the image.

export const CAPABILITY_CONTRACT_VERSION = 1;

export const API_SCOPES = ["authenticated", "operator", "public", "resource", "self", "subject", "tenant"] as const;
export const ROUTE_STATUSES = ["enforced", "planned", "public"] as const;
export const KNOWN_API_ROLES = ["auditor", "memory_admin", "memory_user", "memory_viewer", "platform_operator", "service_worker", "tenant_admin"] as const;

export type ApiRole = (typeof KNOWN_API_ROLES)[number];

/** Every permission each API role holds, exactly as the server computes it. */
export const ROLE_PERMISSIONS: Readonly<Record<ApiRole, readonly string[]>> = {
  "auditor": ["audit:read:self", "audit:read:tenant", "evidence:read", "memory:read:self", "memory:read:tenant", "metrics:read:tenant", "retention:read"],
  "memory_admin": ["audit:read:self", "consent:manage", "memory:approve:tenant", "memory:archive:self", "memory:archive:tenant", "memory:delete:self", "memory:delete:tenant", "memory:read:self", "memory:read:tenant", "memory:reject:tenant", "memory:write:self", "memory:write:tenant", "retention:manage", "retention:read"],
  "memory_user": ["audit:read:self", "memory:archive:self", "memory:delete:self", "memory:read:self", "memory:write:self"],
  "memory_viewer": ["audit:read:self", "memory:read:self"],
  "platform_operator": ["ops:evals:read", "ops:evals:run", "ops:metrics", "ops:readiness", "ops:traces:read", "worker:read"],
  "service_worker": ["worker:read", "worker:replay"],
  "tenant_admin": ["audit:read:self", "audit:read:tenant", "consent:manage", "evidence:read", "memory:approve:tenant", "memory:archive:self", "memory:archive:tenant", "memory:delete:self", "memory:delete:tenant", "memory:read:self", "memory:read:tenant", "memory:reject:tenant", "memory:write:self", "memory:write:tenant", "metrics:read:tenant", "retention:manage", "retention:read", "settings:manage"],
} as const;

export type RouteVariant = {
  readonly action: string;
  readonly selfPermission?: string;
  readonly tenantPermission?: string;
};

export type RouteContract = {
  readonly method: string;
  readonly template: string;
  readonly scope: string;
  readonly status: string;
  readonly permission?: string;
  readonly selfPermission?: string;
  readonly tenantPermission?: string;
  readonly variants?: readonly RouteVariant[];
};

/** Every route the API classifies, with what it requires. */
export const ROUTE_CONTRACTS: readonly RouteContract[] = [
  {"method": "GET", "template": "/", "scope": "public", "status": "public"},
  {"method": "GET", "template": "/api/admin/readiness", "scope": "operator", "status": "enforced", "permission": "ops:readiness"},
  {"method": "GET", "template": "/api/admin/workers/health", "scope": "operator", "status": "enforced", "permission": "worker:read"},
  {"method": "GET", "template": "/api/audit", "scope": "subject", "status": "enforced", "selfPermission": "audit:read:self", "tenantPermission": "audit:read:tenant"},
  {"method": "POST", "template": "/api/chat", "scope": "self", "status": "enforced", "permission": "memory:write:self"},
  {"method": "GET", "template": "/api/evals/latest", "scope": "operator", "status": "enforced", "permission": "ops:evals:read"},
  {"method": "POST", "template": "/api/evals/run", "scope": "operator", "status": "enforced", "permission": "ops:evals:run"},
  {"method": "GET", "template": "/api/evidence/audit/verify", "scope": "tenant", "status": "enforced", "permission": "evidence:read"},
  {"method": "GET", "template": "/api/evidence/deletion/{memory_id}", "scope": "tenant", "status": "enforced", "permission": "evidence:read"},
  {"method": "GET", "template": "/api/evidence/lifecycle/{memory_id}", "scope": "tenant", "status": "enforced", "permission": "evidence:read"},
  {"method": "GET", "template": "/api/evidence/policy", "scope": "tenant", "status": "enforced", "permission": "evidence:read"},
  {"method": "GET", "template": "/api/evidence/response/{trace_id}", "scope": "tenant", "status": "enforced", "permission": "evidence:read"},
  {"method": "GET", "template": "/api/loops", "scope": "authenticated", "status": "enforced"},
  {"method": "GET", "template": "/api/loops/events", "scope": "tenant", "status": "enforced", "permission": "audit:read:tenant"},
  {"method": "GET", "template": "/api/loops/runs", "scope": "tenant", "status": "enforced", "permission": "audit:read:tenant"},
  {"method": "GET", "template": "/api/loops/trace/{trace_id}", "scope": "tenant", "status": "enforced", "permission": "audit:read:tenant"},
  {"method": "GET", "template": "/api/loops/{loop_id}", "scope": "authenticated", "status": "enforced"},
  {"method": "GET", "template": "/api/memories", "scope": "subject", "status": "enforced", "selfPermission": "memory:read:self", "tenantPermission": "memory:read:tenant"},
  {"method": "DELETE", "template": "/api/memories/{memory_id}", "scope": "resource", "status": "enforced", "selfPermission": "memory:delete:self", "tenantPermission": "memory:delete:tenant"},
  {"method": "GET", "template": "/api/memories/{memory_id}", "scope": "resource", "status": "enforced", "selfPermission": "memory:read:self", "tenantPermission": "memory:read:tenant"},
  {"method": "PATCH", "template": "/api/memories/{memory_id}", "scope": "resource", "status": "enforced", "variants": [{"action": "edit", "selfPermission": "memory:write:self", "tenantPermission": "memory:write:tenant"}, {"action": "archive", "selfPermission": "memory:archive:self", "tenantPermission": "memory:archive:tenant"}, {"action": "restore", "selfPermission": "memory:archive:self", "tenantPermission": "memory:archive:tenant"}, {"action": "approve", "tenantPermission": "memory:approve:tenant"}, {"action": "reject", "tenantPermission": "memory:reject:tenant"}]},
  {"method": "GET", "template": "/api/memories/{memory_id}/audit", "scope": "resource", "status": "enforced", "selfPermission": "audit:read:self", "tenantPermission": "audit:read:tenant"},
  {"method": "GET", "template": "/api/memories/{memory_id}/provenance", "scope": "resource", "status": "enforced", "selfPermission": "memory:read:self", "tenantPermission": "memory:read:tenant"},
  {"method": "GET", "template": "/api/metrics", "scope": "tenant", "status": "enforced", "permission": "metrics:read:tenant"},
  {"method": "POST", "template": "/api/retention/consent", "scope": "tenant", "status": "enforced", "permission": "consent:manage"},
  {"method": "GET", "template": "/api/retention/decisions", "scope": "tenant", "status": "enforced", "permission": "retention:read"},
  {"method": "POST", "template": "/api/retention/legal-hold", "scope": "tenant", "status": "enforced", "permission": "retention:manage"},
  {"method": "GET", "template": "/api/retention/memory/{memory_id}", "scope": "tenant", "status": "enforced", "permission": "retention:read"},
  {"method": "POST", "template": "/api/retention/pin", "scope": "tenant", "status": "enforced", "permission": "retention:manage"},
  {"method": "GET", "template": "/api/retention/policies", "scope": "tenant", "status": "enforced", "permission": "retention:read"},
  {"method": "POST", "template": "/api/retention/protect", "scope": "tenant", "status": "enforced", "permission": "retention:manage"},
  {"method": "GET", "template": "/api/traces", "scope": "operator", "status": "enforced", "permission": "ops:traces:read"},
  {"method": "GET", "template": "/docs", "scope": "public", "status": "public"},
  {"method": "GET", "template": "/docs/oauth2-redirect", "scope": "public", "status": "public"},
  {"method": "GET", "template": "/healthz", "scope": "public", "status": "public"},
  {"method": "GET", "template": "/healthz/workers", "scope": "public", "status": "public"},
  {"method": "GET", "template": "/metrics", "scope": "public", "status": "public"},
  {"method": "GET", "template": "/openapi.json", "scope": "public", "status": "public"},
  {"method": "GET", "template": "/readyz", "scope": "public", "status": "public"},
  {"method": "GET", "template": "/redoc", "scope": "public", "status": "public"},
] as const;
