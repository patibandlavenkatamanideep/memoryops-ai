import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Regression guard: no hardcoded tenant identity may return to client code.
 *
 * `lib/api.ts` used to export
 *
 *     export const DEMO_TENANT = "tenant_demo";
 *     export const DEMO_USER   = "user_demo";
 *
 * and attach them to every request from the browser. That is what made the shipped
 * UI single-tenant, tenant-spoofable in devtools, and incompatible with the
 * production profile (it sent no credential, so it only worked against
 * `MEMORYOPS_AUTH_MODE=none`, which production refuses to run).
 *
 * Identity now exists only on the server. The demo identity is allowed to live in
 * `lib/identity.ts` — which is `server-only` and is the module that decides it —
 * but nowhere a browser bundle can reach.
 */

const WEB_ROOT = join(__dirname, "..", "..");

/** Server-side modules that are legitimately allowed to name the demo tenant. */
const SERVER_ONLY_ALLOWLIST = [
  join("lib", "identity.ts"),
  join("lib", "__tests__"),
];

const SEARCH_DIRS = ["app", "components", "lib"];
const SKIP_DIRS = new Set(["node_modules", ".next", "__pycache__"]);

function sourceFiles(dir: string): string[] {
  const abs = join(WEB_ROOT, dir);
  let entries: string[];
  try {
    entries = readdirSync(abs);
  } catch {
    return [];
  }
  const out: string[] = [];
  for (const entry of entries) {
    if (SKIP_DIRS.has(entry)) continue;
    const full = join(abs, entry);
    if (statSync(full).isDirectory()) {
      out.push(...sourceFiles(join(dir, entry)));
    } else if (/\.tsx?$/.test(entry)) {
      out.push(join(dir, entry));
    }
  }
  return out;
}

function allSources(): string[] {
  return SEARCH_DIRS.flatMap(sourceFiles);
}

function isAllowlisted(relative: string): boolean {
  return SERVER_ONLY_ALLOWLIST.some((allowed) => relative.startsWith(allowed));
}

/**
 * Strip comments before matching. Several of these files deliberately describe the
 * old `tenant_demo` bug in prose so the reason for the change survives; prose is
 * not shipped behaviour, and matching it would make these guards unmaintainable.
 */
function code(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

describe("no client-side identity", () => {
  it("finds source files to scan (guard against a silent no-op)", () => {
    expect(allSources().length).toBeGreaterThan(10);
  });

  it("does not export DEMO_TENANT or DEMO_USER anywhere", () => {
    const offenders = allSources().filter((relative) =>
      /export\s+const\s+DEMO_(TENANT|USER)/.test(
        code(readFileSync(join(WEB_ROOT, relative), "utf8")),
      ),
    );
    expect(offenders).toEqual([]);
  });

  it("never hardcodes the demo tenant outside server-only modules", () => {
    const offenders = allSources().filter((relative) => {
      if (isAllowlisted(relative)) return false;
      return code(readFileSync(join(WEB_ROOT, relative), "utf8")).includes("tenant_demo");
    });
    expect(offenders).toEqual([]);
  });

  it("keeps the API client from putting scope into a request", () => {
    // Response *types* legitimately model the API's `tenant_id` fields, so this
    // targets the two ways the old client actually sent scope: interpolating it
    // into a query string, and setting it as a key in a request body/params object.
    const api = code(readFileSync(join(WEB_ROOT, "lib", "api.ts"), "utf8"));
    expect(api).not.toMatch(/tenant_id=/);
    expect(api).not.toMatch(/user_id=/);
    expect(api).not.toMatch(/tenant_id:\s*(DEMO_|`|"|')/);
    expect(api).not.toMatch(/user_id:\s*(DEMO_|`|"|')/);
  });

  it("routes the API client at the same-origin BFF, not the API directly", () => {
    const api = readFileSync(join(WEB_ROOT, "lib", "api.ts"), "utf8");
    expect(api).toContain('API_BASE = "/api/memoryops"');
    // NEXT_PUBLIC_API_URL would put the upstream API origin in the browser bundle
    // and reintroduce direct, unauthenticated browser→API calls.
    const code = api.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    expect(code).not.toContain("NEXT_PUBLIC_API_URL");
  });

  it("decides web mode from a server-only env var", () => {
    const identity = readFileSync(join(WEB_ROOT, "lib", "identity.ts"), "utf8");
    const code = identity.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    expect(code).toContain("process.env.MEMORYOPS_WEB_MODE");
    // Authorization must never key off a value the browser bundle can read.
    expect(code).not.toContain("NEXT_PUBLIC_MEMORYOPS_WEB_MODE");
  });

  it("marks the identity module server-only", () => {
    const identity = readFileSync(join(WEB_ROOT, "lib", "identity.ts"), "utf8");
    expect(identity).toMatch(/^import "server-only";/m);
  });
});
