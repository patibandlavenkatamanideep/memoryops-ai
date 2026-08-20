import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The mobile drawer's keyboard contract.
 *
 * Browser evidence is the real proof here and was captured over CDP; these
 * assertions exist so the contract cannot be deleted silently between browser runs.
 * The test environment is node-only by design (no DOM, no jsdom dependency), so what
 * is checked is the presence of each load-bearing behaviour, not its rendered effect.
 *
 * Two defects motivate it, both measured before the fix at 390px:
 *
 *   - Tab from the last nav link walked into the page *behind* the scrim (6 of 14
 *     stops landed outside the drawer). `aria-modal` tells assistive tech the
 *     background is inert but moves no focus, so an operator could reach and
 *     activate a Delete button hidden underneath the overlay.
 *   - Dismissing with Escape left focus wherever the DOM happened to drop it — in
 *     practice the memories table's scroll region — instead of the toggle.
 */

const src = readFileSync(
  join(__dirname, "..", "components", "shell", "AppShell.tsx"),
  "utf8",
);
const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

describe("drawer keyboard contract", () => {
  it("handles Tab, not only Escape", () => {
    expect(code).toMatch(/event\.key !== "Tab"|event\.key === "Tab"/);
  });

  it("wraps focus at both ends of the drawer", () => {
    // Shift+Tab off the first item must land on the last, and vice versa.
    expect(code).toMatch(/shiftKey/);
    expect(code).toMatch(/preventDefault\(\)/);
  });

  it("pulls focus back in if it is already outside", () => {
    expect(code).toMatch(/contains\(active\)|contains\(document\.activeElement\)/);
  });

  it("remembers what to restore focus to when it opens", () => {
    expect(code).toMatch(/restoreFocusRef/);
    expect(code).toMatch(/document\.activeElement as HTMLElement/);
  });

  it("restores focus on dismissal rather than in an effect cleanup", () => {
    // By cleanup time the panel is unmounted and focus has fallen to <body>, so the
    // "was focus inside?" question is no longer answerable.
    const close = code.slice(code.indexOf("const closeNav"), code.indexOf("const dismissForNavigation"));
    expect(close).toMatch(/restoreFocusRef\.current/);
    expect(close).toMatch(/focus\(\)/);
  });

  it("does not steal focus back when the user is navigating away", () => {
    const dismiss = code.slice(code.indexOf("const dismissForNavigation"));
    const body = dismiss.slice(0, dismiss.indexOf(";") + 1);
    expect(body).not.toMatch(/restoreFocusRef/);
    // The nav links use the non-restoring dismissal.
    expect(code).toMatch(/onNavigate=\{dismissForNavigation\}/);
  });

  it("routes Escape through the restoring path", () => {
    expect(code).toMatch(/if \(event\.key === "Escape"\) \{\s*closeNav\(\);/);
  });

  it("keeps the toggle's expanded state and target wired up", () => {
    const topbar = readFileSync(
      join(__dirname, "..", "components", "shell", "TopBar.tsx"),
      "utf8",
    );
    expect(topbar).toMatch(/aria-expanded=\{navOpen\}/);
    expect(topbar).toMatch(/aria-controls="control-plane-nav"/);
    expect(code).toMatch(/id="control-plane-nav"/);
  });

  it("still locks background scroll while open", () => {
    expect(code).toMatch(/document\.body\.style\.overflow = "hidden"/);
  });
});
