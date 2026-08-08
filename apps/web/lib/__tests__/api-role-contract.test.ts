import { describe, expect, it } from "vitest";

import {
  API_ROLES,
  apiRoleForWebRole,
  UnmappedWebRoleError,
  WEB_TO_API_ROLES,
} from "../apiRoles";
import { ROLES } from "../webRoles";

/**
 * The web and the API had independent role vocabularies, and the BFF minted the
 * web persona name straight into the API credential:
 *
 *     viewer, developer, owner  ->  names the API does not recognise  ->  0 permissions
 *
 * Three of the five human roles had no API access, including `owner`, which the
 * demo identity uses. It was fail-closed but broken.
 *
 * The earlier propagation test asserted the claim *shape* (`roles: [...]`) and
 * therefore could not catch this — the shape was right and the value was wrong.
 * These assert the translation instead.
 */

describe("web persona → API role contract", () => {
  it("maps every web role", () => {
    for (const role of ROLES) {
      expect(WEB_TO_API_ROLES[role], `no mapping for '${role}'`).toBeTruthy();
    }
  });

  it("maps only to roles the API declares", () => {
    const apiRoles = new Set<string>(API_ROLES);
    for (const [webRole, apiRole] of Object.entries(WEB_TO_API_ROLES)) {
      expect(apiRoles.has(apiRole), `'${webRole}' → unknown '${apiRole}'`).toBe(true);
    }
  });

  it("has no mapping the web does not define", () => {
    expect(Object.keys(WEB_TO_API_ROLES).sort()).toEqual([...ROLES].sort());
  });

  it.each([
    ["viewer", "memory_viewer"],
    ["developer", "memory_user"],
    ["auditor", "auditor"],
    ["memory_admin", "memory_admin"],
    ["owner", "tenant_admin"],
  ])("translates %s → %s", (webRole, apiRole) => {
    expect(apiRoleForWebRole(webRole)).toBe(apiRole);
  });

  it("never maps a human persona to the machine role", () => {
    expect(Object.values(WEB_TO_API_ROLES)).not.toContain("service_worker");
  });

  it("fails closed on an unknown persona rather than passing it through", () => {
    // Passing it through is exactly how the original break happened: the API
    // received a name it did not recognise and the caller lost every permission.
    expect(() => apiRoleForWebRole("superuser")).toThrow(UnmappedWebRoleError);
  });
});

describe("both BFF paths use the translation", () => {
  const { readFileSync } = require("node:fs") as typeof import("node:fs");
  const { join } = require("node:path") as typeof import("node:path");
  const WEB_ROOT = join(__dirname, "..", "..");

  function code(path: string): string {
    return readFileSync(join(WEB_ROOT, path), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
  }

  it("mints the translated role into the JWT", () => {
    const src = code("lib/memoryopsToken.ts");
    expect(src).toMatch(/roles:\s*\[\s*apiRoleForWebRole\(/);
    // The raw persona must not reach the API.
    expect(src).not.toMatch(/roles:\s*\[\s*identity\.role\s*\]/);
  });

  it("sets the translated role on the trusted-header path", () => {
    const src = code("app/api/memoryops/[...path]/route.ts");
    expect(src).toMatch(/x-memoryops-roles["']\s*,\s*apiRoleForWebRole\(/);
    expect(src).not.toMatch(/x-memoryops-roles["']\s*,\s*identity\.role\s*\)/);
  });
});
