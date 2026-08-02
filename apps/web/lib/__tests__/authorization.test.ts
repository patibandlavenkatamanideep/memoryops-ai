import { describe, expect, it } from "vitest";

import { hasAtLeast, requiredRole, ROLES } from "../roles";

/**
 * Role gating in the BFF. This is defence in depth on top of the API's own
 * governance — it only ever *removes* access, never grants it.
 */

describe("role ordering", () => {
  it("is least-privilege first", () => {
    expect([...ROLES]).toEqual(["viewer", "developer", "auditor", "memory_admin", "owner"]);
  });

  it("owner satisfies every requirement", () => {
    for (const role of ROLES) expect(hasAtLeast("owner", role)).toBe(true);
  });

  it("viewer satisfies only viewer", () => {
    expect(hasAtLeast("viewer", "viewer")).toBe(true);
    for (const role of ROLES.filter((r) => r !== "viewer")) {
      expect(hasAtLeast("viewer", role)).toBe(false);
    }
  });

  it("is reflexive for every role", () => {
    for (const role of ROLES) expect(hasAtLeast(role, role)).toBe(true);
  });
});

describe("requiredRole", () => {
  it("lets any role read memories but requires admin to mutate them", () => {
    expect(requiredRole("/api/memories", "GET")).toBe("viewer");
    expect(requiredRole("/api/memories/abc", "PATCH")).toBe("memory_admin");
    expect(requiredRole("/api/memories/abc", "DELETE")).toBe("memory_admin");
  });

  it("gates the audit trail and evidence reports behind auditor", () => {
    expect(requiredRole("/api/audit", "GET")).toBe("auditor");
    expect(requiredRole("/api/evidence/deletion-proof", "GET")).toBe("auditor");
  });

  it("restricts eval runs to owner", () => {
    // Running evals is cost-bearing — a denial-of-wallet vector if broadly exposed.
    expect(requiredRole("/api/evals/run", "POST")).toBe("owner");
  });

  it("requires owner for retention mutations but only auditor to read them", () => {
    expect(requiredRole("/api/retention/policies", "GET")).toBe("auditor");
    expect(requiredRole("/api/retention/legal-hold", "POST")).toBe("owner");
  });

  it("treats a viewer as unable to chat (chat writes memory)", () => {
    expect(hasAtLeast("viewer", requiredRole("/api/chat", "POST"))).toBe(false);
    expect(hasAtLeast("developer", requiredRole("/api/chat", "POST"))).toBe(true);
  });

  it("normalises a missing leading slash", () => {
    expect(requiredRole("api/audit", "GET")).toBe("auditor");
  });

  it("defaults unknown paths to the least privileged role, not the most", () => {
    expect(requiredRole("/api/something-new", "GET")).toBe("viewer");
  });
});
