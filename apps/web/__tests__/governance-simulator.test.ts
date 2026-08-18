import { describe, expect, it } from "vitest";

import {
  EXAMPLE_CANDIDATES,
  RULE_SUMMARY,
  SIMPLIFICATIONS,
  simulate,
} from "@/components/public/sections/simulate";

/**
 * The public page's illustrative policy simulation.
 *
 * It is a marketing illustration, but it is an illustration *about refusing to
 * store secrets* — so a credential coming back as anything other than BLOCK would
 * discredit the exact claim the page is making. Rule order is the load-bearing
 * part: "remember my api key just for this session" matches both the credential
 * pattern and the session-scoped pattern, and the credential rule has to win.
 */

describe("the four example candidates behave as the page claims", () => {
  const [metric, credential, sessionScoped, sensitive] = EXAMPLE_CANDIDATES;

  it("saves a durable preference", () => {
    expect(simulate(metric)?.verdict).toBe("SAVE");
  });

  it("blocks a credential", () => {
    expect(simulate(credential)?.verdict).toBe("BLOCK");
  });

  it("keeps an explicitly session-scoped statement out of durable memory", () => {
    expect(simulate(sessionScoped)?.verdict).toBe("SESSION ONLY");
  });

  it("defers high-sensitivity business content to review", () => {
    expect(simulate(sensitive)?.verdict).toBe("REVIEW");
  });
});

describe("credential detection wins over every other rule", () => {
  // Each of these also matches a later pattern. Order is what makes them BLOCK.
  //
  // Values are deliberately inert. The rules key off the *shape* of a credential
  // reference, so a fixture only needs the prefix or the assignment — inventing a
  // realistic-looking token would trip the repository's secret scanner for no
  // extra coverage, and a scanner allowlist is exactly the thing that later hides
  // a real leak.
  const overlapping = [
    "Use this only for this conversation: my key is sk-live-REDACTED.",
    "I always use api_key=REDACTED-TEST-FIXTURE for the staging environment.",
    "Our team password: hunter2correcthorse",
    "Temporarily remember ghp_aaaabbbbccccddddeeeeffff1111222233",
    "-----BEGIN RSA PRIVATE KEY-----",
    "AKIAIOSFODNN7EXAMPLE is our access key id",
  ];

  for (const candidate of overlapping) {
    it(`blocks: ${candidate.slice(0, 44)}…`, () => {
      const decision = simulate(candidate);
      expect(decision?.verdict).toBe("BLOCK");
      expect(decision?.outcome).toContain("Not stored");
    });
  }
});

describe("honesty properties", () => {
  it("returns NO MATCH instead of guessing", () => {
    // Inventing a verdict for unrecognised input would misrepresent the real broker
    // in the one direction that matters — looking more decisive than it is here.
    const decision = simulate("The number seven.");
    expect(decision?.verdict).toBe("NO MATCH");
    expect(decision?.rationale).toContain("real broker");
  });

  it("always names the rule that produced the verdict", () => {
    for (const candidate of [...EXAMPLE_CANDIDATES, "The number seven."]) {
      const decision = simulate(candidate);
      expect(decision?.rule, candidate).toBeTruthy();
    }
  });

  it("returns nothing for empty input rather than a default verdict", () => {
    expect(simulate("")).toBeNull();
    expect(simulate("   ")).toBeNull();
  });

  it("publishes what it does not model, for the UI to render", () => {
    expect(SIMPLIFICATIONS.length).toBeGreaterThanOrEqual(4);
    expect(RULE_SUMMARY.length).toBe(4);
  });
});
