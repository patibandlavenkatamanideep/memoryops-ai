/**
 * The web's capability contract.
 *
 * What this replaces
 * ------------------
 * The BFF ranked personas — viewer < developer < auditor < memory_admin < owner —
 * and asked `hasAtLeast()`. Three consequences, all reproduced before the change:
 *
 *   memory_admin GET /api/evidence/policy  -> ALLOW   (auditor-only at the API)
 *   owner        GET /api/traces           -> ALLOW   (no tenant role holds ops:*)
 *   viewer       GET /api/some/new/route   -> ALLOW   (unknown path fell through)
 *
 * Ranks cannot express orthogonal capabilities, and a fall-through default cannot
 * fail closed.
 */

import { describe, expect, it } from "vitest";

import {
  ROLE_PERMISSIONS,
  ROUTE_CONTRACTS,
  KNOWN_API_ROLES,
} from "../authzCapabilities.generated";
import { NEVER_WEB_ASSIGNABLE, WEB_TO_API_ROLE_MAP } from "../roleMap.generated";
import {
  apiRoleFor,
  can,
  canAttempt,
  deriveActions,
  matchRoute,
  normalizePath,
  uiCapabilities,
} from "../capabilities";

// ── generation + drift ──────────────────────────────────────────────────────
describe("the generated contract", () => {
  it("maps every persona to a role the API actually defines", () => {
    for (const [persona, apiRole] of Object.entries(WEB_TO_API_ROLE_MAP)) {
      expect(KNOWN_API_ROLES, `${persona} -> ${apiRole}`).toContain(apiRole);
      expect(ROLE_PERMISSIONS[apiRole as keyof typeof ROLE_PERMISSIONS]).toBeDefined();
    }
  });

  it("never maps a persona to a machine or deployment role", () => {
    const targets = new Set(Object.values(WEB_TO_API_ROLE_MAP));
    for (const forbidden of NEVER_WEB_ASSIGNABLE) {
      expect(targets, `${forbidden} must not be reachable from the web`).not.toContain(forbidden);
      expect(apiRoleFor(forbidden)).toBeNull();
    }
  });

  it("carries route contracts, not a hand-written subset", () => {
    expect(ROUTE_CONTRACTS.length).toBeGreaterThan(30);
    const templates = ROUTE_CONTRACTS.map((r) => `${r.method} ${r.template}`);
    for (const sentinel of [
      "POST /api/chat",
      "GET /api/memories",
      "PATCH /api/memories/{memory_id}",
      "GET /api/evidence/policy",
      "GET /api/traces",
      "POST /api/evals/run",
    ]) {
      expect(templates).toContain(sentinel);
    }
  });

  it("gives every known API role a permission bundle", () => {
    for (const role of KNOWN_API_ROLES) {
      expect(ROLE_PERMISSIONS[role], role).toBeDefined();
    }
  });
});

// ── route matching ──────────────────────────────────────────────────────────
describe("route matching", () => {
  it("matches a concrete id against a resource template", () => {
    const route = matchRoute("PATCH", "/api/memories/1f0c9e2a-4b7d-4c1e-9a44-1d2f3e4b5c6d");
    expect(route?.template).toBe("/api/memories/{memory_id}");
  });

  it("prefers a literal template over a parameterised one", () => {
    expect(matchRoute("GET", "/api/loops/runs")?.template).toBe("/api/loops/runs");
    expect(matchRoute("GET", "/api/loops/memory.write")?.template).toBe("/api/loops/{loop_id}");
  });

  it("ignores the query string", () => {
    const withQuery = matchRoute("GET", "/api/memories?tenant_id=acme&user_id=alice");
    expect(withQuery?.template).toBe("/api/memories");
  });

  it("normalises traversal and duplicate slashes", () => {
    expect(normalizePath("/healthz/../api/memories")).toBe("/api/memories");
    expect(normalizePath("//api//memories//")).toBe("/api/memories");
    expect(normalizePath("api/memories")).toBe("/api/memories");
  });

  it("returns null for a path the API does not classify", () => {
    expect(matchRoute("GET", "/api/some/brand/new/route")).toBeNull();
  });

  it("returns null for a method the route does not declare", () => {
    expect(matchRoute("DELETE", "/api/chat")).toBeNull();
  });
});

// ── fail closed ─────────────────────────────────────────────────────────────
describe("unknown things are denied", () => {
  it("denies an unclassified path for every persona", () => {
    for (const persona of Object.keys(WEB_TO_API_ROLE_MAP)) {
      const decision = canAttempt({ webRole: persona, method: "GET", path: "/api/new/thing" });
      expect(decision.allowed, persona).toBe(false);
      expect(decision.reason).toContain("no authorization contract");
    }
  });

  it("denies an unknown method", () => {
    expect(can("owner", "DELETE", "/api/chat")).toBe(false);
  });

  it("denies an unknown persona", () => {
    expect(can("superuser", "GET", "/api/memories")).toBe(false);
  });

  it("denies an unknown PATCH status", () => {
    const decision = canAttempt({
      webRole: "owner",
      method: "PATCH",
      path: "/api/memories/abc",
      body: { status: "deleted" },
    });
    expect(decision.allowed).toBe(false);
    expect(decision.reason).toContain("unrecognised change");
  });

  it("denies a PATCH that changes nothing", () => {
    const decision = canAttempt({
      webRole: "owner",
      method: "PATCH",
      path: "/api/memories/abc",
      body: {},
    });
    expect(decision.allowed).toBe(false);
    expect(decision.reason).toContain("changes nothing");
  });

  it("cannot be bypassed by path traversal", () => {
    expect(can("viewer", "GET", "/healthz/../api/evidence/policy")).toBe(false);
  });
});

// ── orthogonality: the reason ranks do not work ─────────────────────────────
describe("auditor and memory_admin are orthogonal", () => {
  it("lets an auditor read evidence, audit and governance timelines", () => {
    expect(can("auditor", "GET", "/api/evidence/policy")).toBe(true);
    expect(can("auditor", "GET", "/api/evidence/audit/verify")).toBe(true);
    expect(can("auditor", "GET", "/api/audit")).toBe(true);
    expect(can("auditor", "GET", "/api/loops/runs")).toBe(true);
  });

  it("refuses an auditor every memory mutation", () => {
    expect(can("auditor", "POST", "/api/chat", {})).toBe(false);
    expect(can("auditor", "DELETE", "/api/memories/abc", {})).toBe(false);
    expect(
      can("auditor", "PATCH", "/api/memories/abc", { content: "rewritten" }),
    ).toBe(false);
    expect(can("auditor", "POST", "/api/retention/legal-hold", { on: true })).toBe(false);
  });

  it("refuses a memory_admin the evidence surfaces", () => {
    // The exact case the ladder allowed: memory_admin outranked auditor, so it
    // passed every auditor check. `evidence:read` is a fixed permission it does not
    // hold, so this is decidable here.
    expect(can("memory_admin", "GET", "/api/evidence/policy")).toBe(false);
    expect(can("memory_admin", "GET", "/api/evidence/audit/verify")).toBe(false);
    expect(can("memory_admin", "GET", "/api/loops/runs")).toBe(false);
  });

  it("still lets a memory_admin attempt audit reads, because self-scope exists", () => {
    // Not a gap — a demonstration of the boundary. `/api/audit` is ownership-scoped:
    // `audit:read:self` for your own rows, `audit:read:tenant` for everyone's.
    // memory_admin holds the former, and the browser cannot tell from the path which
    // scope a request will resolve to. So the attempt is permitted and the API
    // decides: tenant-wide without `audit:read:tenant` is refused there.
    //
    // This is the line between "may this persona attempt this shape" and "is this
    // authorized on this record", and only the API can answer the second.
    expect(can("memory_admin", "GET", "/api/audit")).toBe(true);
    expect(can("memory_admin", "GET", "/api/memories/abc/audit")).toBe(true);
    expect(ROLE_PERMISSIONS.memory_admin).toContain("audit:read:self");
    expect(ROLE_PERMISSIONS.memory_admin).not.toContain("audit:read:tenant");
  });

  it("lets a memory_admin manage tenant memory and retention", () => {
    expect(can("memory_admin", "PATCH", "/api/memories/abc", { content: "fixed" })).toBe(true);
    expect(can("memory_admin", "DELETE", "/api/memories/abc", {})).toBe(true);
    expect(can("memory_admin", "POST", "/api/retention/legal-hold", { on: true })).toBe(true);
    expect(can("memory_admin", "POST", "/api/retention/consent", { status: "withdrawn" })).toBe(
      true,
    );
  });
});

describe("no persona reaches deployment authority", () => {
  it.each(Object.keys(WEB_TO_API_ROLE_MAP))("%s cannot touch ops surfaces", (persona) => {
    expect(can(persona, "GET", "/api/traces")).toBe(false);
    expect(can(persona, "GET", "/api/evals/latest")).toBe(false);
    expect(can(persona, "POST", "/api/evals/run", {})).toBe(false);
    expect(can(persona, "GET", "/api/admin/readiness")).toBe(false);
  });

  it("owner maps to tenant_admin and holds no ops permission", () => {
    expect(apiRoleFor("owner")).toBe("tenant_admin");
    const granted = ROLE_PERMISSIONS.tenant_admin;
    expect(granted.filter((p) => p.startsWith("ops:"))).toEqual([]);
  });
});

// ── per-persona surfaces ────────────────────────────────────────────────────
describe("persona capabilities", () => {
  it("viewer reads its own memory and mutates nothing", () => {
    expect(can("viewer", "GET", "/api/memories")).toBe(true);
    expect(can("viewer", "GET", "/api/memories/abc")).toBe(true);
    expect(can("viewer", "POST", "/api/chat", {})).toBe(false);
    expect(can("viewer", "PATCH", "/api/memories/abc", { content: "x" })).toBe(false);
    expect(can("viewer", "DELETE", "/api/memories/abc", {})).toBe(false);
  });

  it("developer gets self-service memory management", () => {
    expect(can("developer", "POST", "/api/chat", {})).toBe(true);
    expect(can("developer", "PATCH", "/api/memories/abc", { content: "x" })).toBe(true);
    expect(can("developer", "PATCH", "/api/memories/abc", { status: "archived" })).toBe(true);
    expect(can("developer", "DELETE", "/api/memories/abc", {})).toBe(true);
    // Approval is tenant governance: self-service does not include approving itself.
    expect(can("developer", "GET", "/api/evidence/policy")).toBe(false);
  });

  it("owner gets every tenant capability", () => {
    expect(can("owner", "GET", "/api/evidence/policy")).toBe(true);
    expect(can("owner", "PATCH", "/api/memories/abc", { content: "x" })).toBe(true);
    expect(can("owner", "POST", "/api/retention/legal-hold", { on: true })).toBe(true);
    expect(can("owner", "GET", "/api/audit")).toBe(true);
  });
});

// ── PATCH action derivation ─────────────────────────────────────────────────
describe("PATCH actions", () => {
  it("reads edit fields as one edit", () => {
    expect(deriveActions({ content: "x" }).actions).toEqual(["edit"]);
    expect(deriveActions({ importance: 5 }).actions).toEqual(["edit"]);
    expect(deriveActions({ content: "x", importance: 5, confidence: 0.5 }).actions).toEqual([
      "edit",
    ]);
  });

  it("maps unambiguous transitions", () => {
    expect(deriveActions({ status: "archived" }).actions).toEqual(["archive"]);
    expect(deriveActions({ status: "rejected" }).actions).toEqual(["reject"]);
  });

  it("treats status=active as approve-or-restore", () => {
    // The browser cannot know the record's current status, so it cannot know which
    // transition this is. Both candidates are offered; the API resolves it.
    expect(deriveActions({ status: "active" }).actions).toEqual(["approve", "restore"]);
  });

  it("lets a developer attempt its own restore but not an approval it cannot make", () => {
    // `restore` has a self permission, `approve` does not. Holding either candidate
    // is enough to attempt — the API refuses the wrong one after loading the record.
    expect(can("developer", "PATCH", "/api/memories/abc", { status: "active" })).toBe(true);
    // A viewer holds neither.
    expect(can("viewer", "PATCH", "/api/memories/abc", { status: "active" })).toBe(false);
  });

  it("requires every action of a mixed patch", () => {
    const asAdmin = canAttempt({
      webRole: "memory_admin",
      method: "PATCH",
      path: "/api/memories/abc",
      body: { content: "corrected", status: "active" },
    });
    expect(asAdmin.allowed).toBe(true);
    expect(asAdmin.derivedActions).toEqual(["edit", "approve", "restore"]);

    // A viewer holds neither the edit nor either transition.
    expect(
      can("viewer", "PATCH", "/api/memories/abc", { content: "corrected", status: "active" }),
    ).toBe(false);
  });

  it("denies a mixed patch when the edit half is not permitted", () => {
    const decision = canAttempt({
      webRole: "viewer",
      method: "PATCH",
      path: "/api/memories/abc",
      body: { content: "corrected", status: "archived" },
    });
    expect(decision.allowed).toBe(false);
    expect(decision.reason).toContain("edit");
  });
});

// ── UI control visibility ───────────────────────────────────────────────────
describe("uiCapabilities", () => {
  it("gives a viewer read-only affordances", () => {
    const ui = uiCapabilities("viewer");
    expect(ui).toMatchObject({
      canChat: false,
      canEditMemory: false,
      canArchiveOrRestore: false,
      canApproveOrReject: false,
      canDeleteMemory: false,
      canManageRetention: false,
      canReadEvidence: false,
    });
  });

  it("gives a developer self-service mutation without governance", () => {
    const ui = uiCapabilities("developer");
    expect(ui.canChat).toBe(true);
    expect(ui.canEditMemory).toBe(true);
    expect(ui.canArchiveOrRestore).toBe(true);
    expect(ui.canDeleteMemory).toBe(true);
    // Approving your own pending memory would defeat the queue that held it.
    expect(ui.canApproveOrReject).toBe(false);
    expect(ui.canManageRetention).toBe(false);
    expect(ui.canReadEvidence).toBe(false);
  });

  it("gives an auditor evidence and timelines, and no mutation control", () => {
    const ui = uiCapabilities("auditor");
    expect(ui.canReadEvidence).toBe(true);
    expect(ui.canReadGovernanceTimelines).toBe(true);
    expect(ui.canEditMemory).toBe(false);
    expect(ui.canDeleteMemory).toBe(false);
    expect(ui.canApproveOrReject).toBe(false);
    expect(ui.canManageRetention).toBe(false);
    expect(ui.canChat).toBe(false);
  });

  it("gives a memory_admin lifecycle and retention, and no evidence", () => {
    const ui = uiCapabilities("memory_admin");
    expect(ui.canEditMemory).toBe(true);
    expect(ui.canApproveOrReject).toBe(true);
    expect(ui.canDeleteMemory).toBe(true);
    expect(ui.canManageRetention).toBe(true);
    // The orthogonality, at the UI layer too.
    expect(ui.canReadEvidence).toBe(false);
  });

  it("gives an owner every tenant control", () => {
    const ui = uiCapabilities("owner");
    for (const [name, allowed] of Object.entries(ui)) {
      expect(allowed, name).toBe(true);
    }
  });

  it("gives an unknown persona nothing", () => {
    const ui = uiCapabilities("superuser");
    for (const [name, allowed] of Object.entries(ui)) {
      expect(allowed, name).toBe(false);
    }
  });
});
