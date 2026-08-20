import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Long unbroken tokens must never push the document sideways.
 *
 * MemoryOps renders a lot of verbatim, server-supplied text: provenance excerpts,
 * audit reasons, loop event reasons, memory content. Real messages contain URLs and
 * opaque identifiers, and a token with no break opportunity paints straight past its
 * container — `getBoundingClientRect` still reports the box as in-bounds while the
 * *document* grows, which is why this is easy to ship without noticing.
 *
 * It was shipped: a memory whose source excerpt held a runbook URL gave
 * `/memories/{id}` 78px of horizontal overflow at 360px, traced to `SourceQuote`.
 *
 * These assertions are structural because the failure is structural — the fix is a
 * wrapping declaration on the element that renders free text, and its absence is
 * exactly what regresses.
 */

const WEB_ROOT = join(__dirname, "..");
const read = (...p: string[]) => readFileSync(join(WEB_ROOT, ...p), "utf8");

/** Tailwind classes that give a long token somewhere to break. */
const WRAPS = /break-words|break-all|overflow-wrap|\[overflow-wrap|truncate|line-clamp|overflow-hidden|overflow-auto|whitespace-pre-wrap/;

describe("primitives that render free text can break long tokens", () => {
  const cases: [string, string[], string][] = [
    ["SourceQuote", ["components", "ui", "Values.tsx"], "SourceQuote"],
    ["KeyValue", ["components", "ui", "Values.tsx"], "KeyValue"],
    ["TimelineItem description", ["components", "ui", "Timeline.tsx"], "description ?"],
    ["ErrorState detail", ["components", "ui", "States.tsx"], "detail ?"],
  ];

  for (const [label, path, marker] of cases) {
    it(`${label} declares a wrapping rule`, () => {
      const src = read(...path);
      const start = src.indexOf(marker);
      expect(start, `${marker} not found`).toBeGreaterThan(-1);
      // Look at the JSX immediately following the marker, where the class lives.
      expect(src.slice(start, start + 700), label).toMatch(WRAPS);
    });
  }
});

describe("MonoId keeps the full identifier addressable", () => {
  it("clips with CSS rather than slicing the value", () => {
    const src = read("components", "ui", "Values.tsx");
    const block = src.slice(src.indexOf("export function MonoId"));
    // Truncating with `.slice()` would make a copied id silently wrong.
    expect(block.slice(0, 900)).not.toMatch(/value\.slice\(/);
    expect(block.slice(0, 900)).toMatch(/overflow-hidden/);
    expect(block.slice(0, 900)).toMatch(/title=\{value\}/);
  });
});

describe("the registry does not strand columns off-screen on small viewports", () => {
  const src = readFileSync(join(WEB_ROOT, "components", "memories", "MemoryTable.tsx"), "utf8");

  it("renders a card presentation below the table breakpoint", () => {
    expect(src).toMatch(/md:hidden/);
    expect(src).toMatch(/hidden md:block/);
  });

  it("the card carries every field the row does", () => {
    const card = src.slice(src.indexOf("md:hidden"), src.indexOf("hidden md:block"));
    for (const field of [
      "StatusBadge",
      "memory_type",
      "sensitivity",
      "importance",
      "confidence",
      "source.kind",
      "MemoryActions",
    ]) {
      expect(card, field).toContain(field);
    }
  });

  it("removes the inactive presentation instead of only hiding it visually", () => {
    // `sr-only` would leave both in the accessibility tree; `hidden` does not.
    expect(src).not.toMatch(/sr-only[^"]*md:block/);
  });
});

describe("no public component reintroduces an unwrapped free-text block", () => {
  function walk(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
      const full = join(dir, e.name);
      return e.isDirectory() ? walk(full) : /\.tsx?$/.test(e.name) ? [full] : [];
    });
  }

  it("keeps whitespace-nowrap off long-form text containers", () => {
    // nowrap belongs on short enum-shaped values (badges, table headers), never on
    // a paragraph of server-supplied prose.
    const offenders: string[] = [];
    for (const file of walk(join(WEB_ROOT, "components"))) {
      const src = readFileSync(file, "utf8");
      for (const m of src.matchAll(/<p[^>]*className="([^"]*whitespace-nowrap[^"]*)"/g)) {
        offenders.push(`${file.slice(WEB_ROOT.length + 1)}: ${m[1]}`);
      }
    }
    expect(offenders, offenders.join("\n")).toEqual([]);
  });
});
