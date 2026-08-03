import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The BFF must hand the API a role the API actually reads, and the browser must
 * never be able to supply one.
 *
 * Two integration bugs this locks down:
 *
 * 1. The minted JWT carried a singular `role` claim while the API's adapter reads
 *    `roles` by default. The claim never matched, so every authenticated web user
 *    — including auditors and admins — reached the API with no recognised role and
 *    was downgraded to the least-privileged default. The web tier enforced roles
 *    and the API did not see them.
 *
 * 2. The trusted-header path sent tenant and user but no role header at all, with
 *    the same effect.
 *
 * Asserted against the source because these are contract details between two
 * services: a runtime test in this package cannot see what the API decodes.
 */

const WEB_ROOT = join(__dirname, "..", "..");
const token = readFileSync(join(WEB_ROOT, "lib/memoryopsToken.ts"), "utf8");
const route = readFileSync(
  join(WEB_ROOT, "app/api/memoryops/[...path]/route.ts"),
  "utf8",
);

function code(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

describe("BFF → API role propagation", () => {
  it("mints the plural `roles` claim the API reads", () => {
    const src = code(token);
    expect(src).toMatch(/roles:\s*\[/);
  });

  it("does not mint a singular `role` claim the API ignores", () => {
    const src = code(token);
    expect(src).not.toMatch(/^\s*role:\s/m);
  });

  it("sets the role header on the trusted-header path", () => {
    const src = code(route);
    expect(src).toMatch(/headers\.set\(\s*["']x-memoryops-roles["']/);
  });

  it("derives the role from the server-resolved identity, never the request", () => {
    const src = code(route);
    // Translated, not raw: this originally asserted `identity.role` directly, which
    // is the untranslated persona the API does not recognise. Shape was right,
    // value was wrong — see api-role-contract.test.ts.
    expect(src).toMatch(/x-memoryops-roles["']\s*,\s*apiRoleForWebRole\(identity\.role\)/);
  });
});

describe("browser cannot inject identity headers", () => {
  const blocked = code(route);

  it.each([
    "x-memoryops-tenant",
    "x-memoryops-user",
    "x-memoryops-roles",
    "x-memoryops-actor-type",
    "authorization",
    "cookie",
  ])("strips inbound %s", (header) => {
    expect(blocked).toContain(`"${header}"`);
  });

  it("strips inbound headers before setting the server's own", () => {
    const stripIndex = blocked.indexOf("BLOCKED_REQUEST_HEADERS");
    const setIndex = blocked.indexOf('headers.set("x-memoryops-roles"');
    expect(stripIndex).toBeGreaterThan(-1);
    expect(setIndex).toBeGreaterThan(stripIndex);
  });
});
