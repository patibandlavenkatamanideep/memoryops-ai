import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { isChromeless } from "@/components/shell/navigation";

/**
 * Landmark ownership between the two shells.
 *
 * `/` renders `PublicShell` inside `AppShell`'s chromeless branch. When *both*
 * emitted `<main id="main-content">`, the landing page shipped two nested `<main>`
 * elements and a duplicate DOM id — so landmark navigation offered a phantom
 * region and the skip link resolved to the outer wrapper instead of the content.
 *
 * The rule this locks in: a chromeless route supplies its own landmarks, and
 * `AppShell` supplies them only for routes it actually wraps in chrome.
 */

const WEB_ROOT = join(__dirname, "..");
const read = (...p: string[]) => readFileSync(join(WEB_ROOT, ...p), "utf8");

/** Strip comments so prose describing the bug does not count as code. */
function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

describe("main landmark ownership", () => {
  it("AppShell emits exactly one <main>, in its chrome branch only", () => {
    const mains = code(read("components", "shell", "AppShell.tsx")).match(/<main\b/g) ?? [];
    expect(mains).toHaveLength(1);
  });

  it("the chromeless branch returns children without wrapping them", () => {
    const src = code(read("components", "shell", "AppShell.tsx"));
    const branch = src.slice(src.indexOf("isChromeless(pathname)"), src.indexOf("return (\n    <div"));
    expect(branch).not.toMatch(/<main\b/);
  });

  it("every chromeless route's own shell supplies a main landmark", () => {
    // `/` -> PublicShell, `/signin` -> the page itself.
    for (const [label, source] of [
      ["PublicShell", read("components", "public", "PublicShell.tsx")],
      ["signin page", read("app", "signin", "page.tsx")],
    ] as const) {
      const mains = code(source).match(/<main\b/g) ?? [];
      expect(mains, label).toHaveLength(1);
      expect(code(source), label).toContain('id="main-content"');
    }
  });

  it("routes that keep the chrome do not also ship their own main", () => {
    for (const page of [
      ["app", "chat", "page.tsx"],
      ["app", "memories", "page.tsx"],
      ["app", "governance", "page.tsx"],
      ["app", "audit", "page.tsx"],
      ["app", "loops", "page.tsx"],
      ["app", "admin", "page.tsx"],
      ["app", "architecture", "page.tsx"],
    ]) {
      expect(code(read(...page)), page.join("/")).not.toMatch(/<main\b/);
    }
  });
});

describe("isChromeless still matches only the two intended routes", () => {
  it("covers / and /signin", () => {
    expect(isChromeless("/")).toBe(true);
    expect(isChromeless("/signin")).toBe(true);
  });

  it("leaves every application surface in the chrome", () => {
    for (const route of [
      "/chat",
      "/memories",
      "/memories/mem_01H8XYZ",
      "/governance",
      "/audit",
      "/loops",
      "/admin",
      "/architecture",
    ]) {
      expect(isChromeless(route), route).toBe(false);
    }
  });
});
