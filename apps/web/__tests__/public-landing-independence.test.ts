import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Regression guard: the public landing page must render for an anonymous visitor.
 *
 * v2.6 Stage B makes `/` publicly reachable. A page that is reachable without a
 * session but *needs* one does not fail politely — `resolveIdentity()` throws
 * `UnauthenticatedError` in authenticated mode, and an authenticated API call
 * through the BFF returns 401. Either turns the new public surface into an error
 * page for exactly the visitors it was opened for, and only in production, since
 * demo mode resolves an identity for everyone.
 *
 * The realistic way this regresses is not someone importing `lib/api` into
 * `app/page.tsx` on purpose. It is a later stage adding a "live memory count" or a
 * usage widget to the landing page, several components deep. So the whole
 * first-party import graph is walked, not just the page's own import list.
 *
 * This asserts a *dependency* property, not a rendering one. It is deliberately
 * cheap and static; the end-to-end evidence is the anonymous route matrix in
 * middleware-route-protection.test.ts plus the recorded HTTP check.
 */

const WEB_ROOT = join(__dirname, "..");

/** Entry points that must stay renderable with no session. */
const PUBLIC_ENTRY_POINTS = [
  join("app", "page.tsx"),
  join("app", "architecture", "page.tsx"),
];

/**
 * Modules that make a page session-dependent.
 *
 * `lib/api` is the browser's client for the BFF, which is authenticated on every
 * route. `lib/identity` and `auth` resolve the session itself. `RootLayout` uses
 * the latter two legitimately — it degrades `UnauthenticatedError` to null — but a
 * *page* doing so has no such contract.
 */
const SESSION_DEPENDENT = ["lib/api", "lib/identity", "auth"];

/** Resolve a first-party `@/…` specifier to a file on disk. */
function resolveFirstParty(specifier: string): string | null {
  if (!specifier.startsWith("@/")) return null;
  const base = join(WEB_ROOT, specifier.slice(2));
  for (const candidate of [
    `${base}.ts`,
    `${base}.tsx`,
    join(base, "index.ts"),
    join(base, "index.tsx"),
  ]) {
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

function importsOf(file: string): string[] {
  const source = readFileSync(file, "utf8");
  // Comments are stripped first so a docstring that *names* a forbidden module in
  // order to explain why it is absent does not register as an import.
  const code = source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  return [...code.matchAll(/from\s+["']([^"']+)["']/g)].map((m) => m[1]);
}

/** Every first-party module reachable from `entry`, including itself. */
function importGraph(entry: string): Map<string, string[]> {
  const graph = new Map<string, string[]>();
  const queue = [join(WEB_ROOT, entry)];

  while (queue.length > 0) {
    const file = queue.pop() as string;
    if (graph.has(file)) continue;
    const specifiers = importsOf(file);
    graph.set(file, specifiers);
    for (const specifier of specifiers) {
      const resolved = resolveFirstParty(specifier);
      if (resolved && !graph.has(resolved)) queue.push(resolved);
    }
  }
  return graph;
}

describe("public landing pages are session-independent", () => {
  for (const entry of PUBLIC_ENTRY_POINTS) {
    it(`${entry} reaches no session-dependent module`, () => {
      const graph = importGraph(entry);
      const offenders: string[] = [];

      for (const [file, specifiers] of graph) {
        for (const specifier of specifiers) {
          const bare = specifier.replace(/^@\//, "");
          if (SESSION_DEPENDENT.some((m) => bare === m || bare.startsWith(`${m}/`))) {
            offenders.push(`${file.slice(WEB_ROOT.length + 1)} -> ${specifier}`);
          }
        }
      }

      expect(offenders, offenders.join("\n")).toEqual([]);
    });
  }

  it("walks past the entry file rather than only checking it", () => {
    // Guards the guard: if resolution silently broke, every assertion above would
    // pass vacuously on a one-node graph.
    const graph = importGraph(join("app", "page.tsx"));
    expect(graph.size).toBeGreaterThan(3);
  });

  it("still sees the session-dependent modules it is looking for", () => {
    // The layout legitimately depends on identity. If this stops being detected,
    // the matcher has drifted and the assertions above mean nothing.
    const graph = importGraph(join("app", "layout.tsx"));
    const specifiers = [...graph.values()].flat().map((s) => s.replace(/^@\//, ""));
    expect(specifiers).toContain("lib/identity");
  });
});
