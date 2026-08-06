/**
 * Capability evaluation for the BFF and the UI.
 *
 * Replaces the ordinal role ladder (`hasAtLeast`). Ranking personas made
 * `memory_admin` outrank `auditor` — so managing memory implied reading the evidence
 * of who managed it, which the API has never allowed — and made `owner` outrank
 * everything, including deployment surfaces no tenant role can reach. It also
 * defaulted unknown paths to the least-privileged role, so a newly added endpoint was
 * *readable* rather than denied.
 *
 * What this answers
 * -----------------
 *   May this persona attempt this route and action shape?
 *
 * What it deliberately does NOT answer:
 *
 *   Is this operation authorized on this record?
 *
 * The browser does not know the stored owner of a memory, whether the caller is
 * acting on their own record or someone else's, the record's current lifecycle
 * status, whether `status="active"` means restore or approve, or anything about legal
 * hold, revisions or consent. Claiming otherwise would be a second authorization
 * model that is wrong in ways nobody can see. This only ever *removes* access; the
 * API remains authoritative and re-decides everything after loading the record.
 */

import {
  ROLE_PERMISSIONS,
  ROUTE_CONTRACTS,
  type ApiRole,
  type RouteContract,
} from "@/lib/authzCapabilities.generated";
import { NEVER_WEB_ASSIGNABLE, WEB_TO_API_ROLE_MAP } from "@/lib/roleMap.generated";

export type WebRole = keyof typeof WEB_TO_API_ROLE_MAP;

export type CapabilityDecision = {
  readonly allowed: boolean;
  /** The route template that matched, if any. */
  readonly matchedTemplate: string | null;
  readonly apiRole: ApiRole | null;
  /** Permissions the persona needed to hold for this attempt. */
  readonly requiredPermissions: readonly string[];
  /** For variant routes: which actions the body appears to request. */
  readonly derivedActions: readonly string[];
  readonly reason: string;
};

/** Normalize a request path so matching cannot be bypassed by shape. */
export function normalizePath(raw: string): string {
  const withoutQuery = raw.split("?")[0].split("#")[0];
  const leading = withoutQuery.startsWith("/") ? withoutQuery : `/${withoutQuery}`;
  // Resolve `.` / `..` so `/healthz/../api/memories` cannot dodge a prefix rule, and
  // collapse repeated slashes so `//api//memories` matches one template.
  const parts: string[] = [];
  for (const segment of leading.split("/")) {
    if (segment === "" || segment === ".") continue;
    if (segment === "..") {
      parts.pop();
      continue;
    }
    parts.push(segment);
  }
  const path = `/${parts.join("/")}`;
  return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
}

function templateMatches(template: string, path: string): boolean {
  const t = template.split("/").filter(Boolean);
  const p = path.split("/").filter(Boolean);
  if (t.length !== p.length) return false;
  return t.every((segment, i) =>
    segment.startsWith("{") && segment.endsWith("}") ? p[i].length > 0 : segment === p[i],
  );
}

/** The route contract for a method+path, or null when the API declares none. */
export function matchRoute(method: string, path: string): RouteContract | null {
  const normalized = normalizePath(path);
  const verb = method.toUpperCase();
  const candidates = ROUTE_CONTRACTS.filter(
    (r) => r.method === verb && templateMatches(r.template, normalized),
  );
  if (candidates.length === 0) return null;
  // Prefer a literal template over one with a parameter, so `/api/loops/runs` is not
  // served by `/api/loops/{loop_id}`.
  const literal = candidates.find((r) => !r.template.includes("{"));
  return literal ?? candidates[0];
}

export function apiRoleFor(webRole: string): ApiRole | null {
  const mapped = (WEB_TO_API_ROLE_MAP as Record<string, string>)[webRole];
  if (!mapped) return null;
  // A persona must never resolve to a machine or deployment role. The mapping is
  // generated and tested, so this is the second line rather than the first.
  if ((NEVER_WEB_ASSIGNABLE as readonly string[]).includes(mapped)) return null;
  return mapped as ApiRole;
}

export function permissionsFor(role: ApiRole): readonly string[] {
  return ROLE_PERMISSIONS[role] ?? [];
}

export function roleHas(role: ApiRole, permission: string): boolean {
  return permissionsFor(role).includes(permission);
}

/** Fields whose presence means the body is editing the memory's substance. */
const EDIT_FIELDS = ["content", "importance", "confidence"] as const;

/**
 * Which governance actions a PATCH body appears to request.
 *
 * `status: "active"` is genuinely ambiguous from here: it is `approve` from
 * `pending` and `restore` from `archived`, and the browser does not know which. Both
 * candidates are returned, and the caller is allowed to attempt when the persona
 * holds *either* — the API loads the record, resolves the real transition, and
 * refuses the wrong authority. Denying both would break legitimate self-restore;
 * assuming one would either over- or under-permit.
 */
export function deriveActions(body: unknown): { actions: string[]; unknown: string[] } {
  const actions: string[] = [];
  const unknownParts: string[] = [];
  if (typeof body !== "object" || body === null) {
    return { actions, unknown: ["<non-object body>"] };
  }
  const record = body as Record<string, unknown>;

  if (EDIT_FIELDS.some((f) => record[f] !== undefined && record[f] !== null)) {
    actions.push("edit");
  }

  const status = record.status;
  if (status !== undefined && status !== null) {
    if (status === "archived") actions.push("archive");
    else if (status === "rejected") actions.push("reject");
    else if (status === "active") actions.push("approve", "restore");
    else unknownParts.push(`status=${String(status)}`);
  }

  return { actions, unknown: unknownParts };
}

function deny(reason: string, extra: Partial<CapabilityDecision> = {}): CapabilityDecision {
  return {
    allowed: false,
    matchedTemplate: null,
    apiRole: null,
    requiredPermissions: [],
    derivedActions: [],
    reason,
    ...extra,
  };
}

/**
 * May this persona attempt this request?
 *
 * Unknown method, unknown path, unknown PATCH field and unknown transition all deny.
 * A route the API has classified but not yet enforced is still evaluated against its
 * declared permission — the web has no reason to be laxer than the stated intent.
 */
export function canAttempt(input: {
  webRole: string;
  method: string;
  path: string;
  body?: unknown;
}): CapabilityDecision {
  const apiRole = apiRoleFor(input.webRole);
  if (apiRole === null) {
    return deny(`unknown or non-web-assignable persona '${input.webRole}'`);
  }

  const route = matchRoute(input.method, input.path);
  if (route === null) {
    // Fail closed. The old policy fell through to the least-privileged role, which
    // for a GET meant an unrecognised endpoint was readable by everyone.
    return deny(`no authorization contract for ${input.method.toUpperCase()} ${input.path}`, {
      apiRole,
    });
  }

  const base = { matchedTemplate: route.template, apiRole };

  if (route.scope === "public" || route.status === "public") {
    return { ...base, allowed: true, requiredPermissions: [], derivedActions: [], reason: "public" };
  }
  if (route.scope === "authenticated") {
    return {
      ...base,
      allowed: true,
      requiredPermissions: [],
      derivedActions: [],
      reason: "any authenticated caller",
    };
  }

  // Variant routes (PATCH): every action the body requests must be permitted.
  if (route.variants && route.variants.length > 0) {
    const { actions, unknown } = deriveActions(input.body);
    if (unknown.length > 0) {
      return deny(`unrecognised change requested: ${unknown.join(", ")}`, {
        ...base,
        derivedActions: actions,
      });
    }
    if (actions.length === 0) {
      return deny("request changes nothing", { ...base });
    }

    const required: string[] = [];
    // `approve`/`restore` are alternative readings of the same body, so holding
    // either is enough; every *other* action must be held outright.
    const ambiguous = new Set(["approve", "restore"]);
    const definite = actions.filter((a) => !ambiguous.has(a));
    const candidates = actions.filter((a) => ambiguous.has(a));

    for (const action of definite) {
      const variant = route.variants.find((v) => v.action === action);
      if (!variant) {
        return deny(`route declares no '${action}' action`, { ...base, derivedActions: actions });
      }
      const options = [variant.selfPermission, variant.tenantPermission].filter(
        (p): p is string => Boolean(p),
      );
      if (!options.some((p) => roleHas(apiRole, p))) {
        return deny(`missing permission for '${action}'`, {
          ...base,
          derivedActions: actions,
          requiredPermissions: options,
        });
      }
      required.push(...options);
    }

    if (candidates.length > 0) {
      const options = candidates.flatMap((action) => {
        const variant = route.variants?.find((v) => v.action === action);
        return [variant?.selfPermission, variant?.tenantPermission].filter(
          (p): p is string => Boolean(p),
        );
      });
      if (options.length === 0) {
        return deny("route declares none of the candidate transitions", {
          ...base,
          derivedActions: actions,
        });
      }
      if (!options.some((p) => roleHas(apiRole, p))) {
        return deny(`missing permission for ${candidates.join(" or ")}`, {
          ...base,
          derivedActions: actions,
          requiredPermissions: options,
        });
      }
      required.push(...options);
    }

    return {
      ...base,
      allowed: true,
      derivedActions: actions,
      requiredPermissions: [...new Set(required)],
      reason: "persona holds a permission for every requested action",
    };
  }

  // Ownership-scoped routes: the browser cannot know the record's owner, so holding
  // either the self or the tenant permission is enough to *attempt*. The API decides
  // from the stored owner.
  const ownership = [route.selfPermission, route.tenantPermission].filter(
    (p): p is string => Boolean(p),
  );
  if (ownership.length > 0) {
    if (!ownership.some((p) => roleHas(apiRole, p))) {
      return deny("persona holds neither the self nor the tenant permission", {
        ...base,
        requiredPermissions: ownership,
      });
    }
    return {
      ...base,
      allowed: true,
      requiredPermissions: ownership,
      derivedActions: [],
      reason: "persona may attempt against its own or the tenant's records",
    };
  }

  if (route.permission) {
    if (!roleHas(apiRole, route.permission)) {
      return deny(`persona lacks ${route.permission}`, {
        ...base,
        requiredPermissions: [route.permission],
      });
    }
    return {
      ...base,
      allowed: true,
      requiredPermissions: [route.permission],
      derivedActions: [],
      reason: "persona holds the required permission",
    };
  }

  // Classified, but naming no permission: refuse rather than guess.
  return deny("route contract names no permission", { ...base });
}

/** Convenience for UI controls: may this persona attempt this at all? */
export function can(webRole: string, method: string, path: string, body?: unknown): boolean {
  return canAttempt({ webRole, method, path, body }).allowed;
}

/**
 * Control-group visibility for the UI, derived from the same contract the BFF uses.
 *
 * Not a second table. Every field is a `canAttempt` call against the route the
 * control actually invokes, so a UI affordance cannot claim a capability the proxy
 * would refuse — and cannot silently diverge when the API's contract changes.
 *
 * Hiding a control is a usability decision, never a security one: the BFF refuses
 * independently, and the API refuses again after loading the record.
 */
export type UiCapabilities = {
  readonly canChat: boolean;
  readonly canEditMemory: boolean;
  readonly canArchiveOrRestore: boolean;
  readonly canApproveOrReject: boolean;
  readonly canDeleteMemory: boolean;
  readonly canManageRetention: boolean;
  readonly canReadEvidence: boolean;
  readonly canReadGovernanceTimelines: boolean;
};

const ANY_MEMORY = "/api/memories/00000000-0000-0000-0000-000000000000";

export function uiCapabilities(webRole: string): UiCapabilities {
  const attempt = (method: string, path: string, body?: unknown) =>
    canAttempt({ webRole, method, path, body }).allowed;

  return {
    canChat: attempt("POST", "/api/chat", { message: "" }),
    canEditMemory: attempt("PATCH", ANY_MEMORY, { content: "" }),
    canArchiveOrRestore: attempt("PATCH", ANY_MEMORY, { status: "archived" }),
    // `approve` declares no self permission at the API, so this is true only for a
    // persona holding tenant approval — not for anyone who can merely edit.
    canApproveOrReject: attempt("PATCH", ANY_MEMORY, { status: "rejected" }),
    canDeleteMemory: attempt("DELETE", ANY_MEMORY, {}),
    canManageRetention: attempt("POST", "/api/retention/legal-hold", { on: true }),
    canReadEvidence: attempt("GET", "/api/evidence/policy"),
    canReadGovernanceTimelines: attempt("GET", "/api/loops/runs"),
  };
}
