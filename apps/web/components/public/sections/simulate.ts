/**
 * The public page's illustrative policy simulation.
 *
 * This is **not** the policy broker. It is five regular expressions running in the
 * visitor's browser, and it exists to make the *shape* of a governed decision
 * tangible — a candidate goes in, a verdict and a reason come out — without calling
 * the real API.
 *
 * Three deliberate constraints:
 *
 *  1. It runs entirely client-side and reaches nothing. The public page must stay
 *     session-independent (see `__tests__/public-landing-independence.test.ts`), and
 *     a marketing page must never be able to write to a tenant's memory.
 *  2. Every result names the rule that produced it. A visitor who sees
 *     "matched: credential-shaped token" understands they are looking at a pattern
 *     match, not a judgement — which is a more honest illustration than a confident
 *     verdict with no visible reasoning.
 *  3. Unmatched input returns `NO_MATCH` rather than guessing. The real broker
 *     scores utility, confidence, duplication and tenant policy; inventing a verdict
 *     here would misrepresent it in the one direction that matters.
 *
 * The real broker's inputs are listed in `SIMPLIFICATIONS` and shown in the UI.
 */

export type SimulatedVerdict =
  | "SAVE"
  | "BLOCK"
  | "SESSION ONLY"
  | "REVIEW"
  | "NO MATCH";

export interface SimulatedDecision {
  readonly verdict: SimulatedVerdict;
  /** The pattern that fired, in plain words. Shown to the visitor. */
  readonly rule: string;
  readonly rationale: string;
  /** What the runtime would do with the candidate. */
  readonly outcome: string;
}

interface Rule {
  readonly pattern: RegExp;
  readonly label: string;
  readonly decision: Omit<SimulatedDecision, "rule">;
}

/**
 * Ordered. The first match wins, and credentials are checked first on purpose:
 * "remember my api key for this session" must block, not become session-scoped.
 */
const RULES: readonly Rule[] = [
  {
    // The word boundary is per-alternative, not wrapped around the whole group:
    // `\b` cannot match before the `-` in `-----BEGIN`, so a hoisted `\b(…)` let
    // PEM private-key headers fall through to NO MATCH entirely.
    pattern:
      /(\bsk-[a-z0-9]|\bAKIA[0-9A-Z]|\bghp_|\bxox[baprs]-|-----BEGIN|\bpassword\s*[:=]|\bapi[\s_-]?key|\bsecret[\s_-]?key|\bbearer\s+[a-z0-9._-]{8})/i,
    label: "credential-shaped token",
    decision: {
      verdict: "BLOCK",
      rationale:
        "Content that looks like a secret is refused before storage. Nothing is written, so it can never be retrieved or leak into a later answer.",
      outcome: "Not stored. The refusal itself is audited.",
    },
  },
  {
    pattern:
      /\b(only for (this|the current)|just for (this|now)|this (conversation|chat|session) only|don'?t (remember|save|store)|do not (remember|save|store)|temporar(y|ily))\b/i,
    label: "session-scoped instruction",
    decision: {
      verdict: "SESSION ONLY",
      rationale:
        "The user scoped this to the current conversation. It can inform this session without becoming durable memory.",
      outcome: "Held for the session. Nothing persists after it ends.",
    },
  },
  {
    pattern:
      /\b(acquisition|acquire|merger|layoffs?|redundanc(y|ies)|salary|compensation|termination|lawsuit|litigation|confidential|unreleased|under embargo|nda)\b/i,
    label: "high-sensitivity business content",
    decision: {
      verdict: "REVIEW",
      rationale:
        "Sensitive enough that an automatic write is the wrong default. It waits in the approval queue for a human decision.",
      outcome: "Queued for approval. Not retrievable until approved.",
    },
  },
  {
    pattern:
      /\b(prefer|prefers|preference|always|never|use|uses|using|default to|stick to|we run|i am|i'?m|my|our|team)\b/i,
    label: "durable preference or working fact",
    decision: {
      verdict: "SAVE",
      rationale:
        "A stable, low-sensitivity statement that stays useful beyond this turn. Stored as typed memory with its source.",
      outcome: "Stored, provenanced, and retrievable within this tenant.",
    },
  },
];

const NO_MATCH: SimulatedDecision = {
  verdict: "NO MATCH",
  rule: "no illustrative rule matched",
  rationale:
    "This simplified illustration only recognises the four patterns above. The real broker would still reach a verdict here — it scores utility, confidence, duplication and tenant policy, none of which are modelled on this page.",
  outcome: "Undetermined by this illustration.",
};

/** What this simulation leaves out. Rendered next to it, not hidden in a comment. */
export const SIMPLIFICATIONS: readonly string[] = [
  "Sensitivity tiers and per-tenant policy packs",
  "Confidence and importance scoring",
  "Duplicate detection and reinforcement of existing memory",
  "Legal hold, consent state and retention windows",
  "The LLM-assisted extractor that produces candidates in the first place",
];

/** The four candidates offered as one-click examples. */
export const EXAMPLE_CANDIDATES: readonly string[] = [
  "User prefers metric units in all explanations.",
  "My OpenAI key is sk-live-8f3a2c laid out in the config.",
  "Use this only for this conversation: the client is called Northwind.",
  "The company acquisition target is a competitor in the logistics space.",
];

export function simulate(candidate: string): SimulatedDecision | null {
  const text = candidate.trim();
  if (!text) return null;

  for (const rule of RULES) {
    if (rule.pattern.test(text)) {
      return { ...rule.decision, rule: `matched: ${rule.label}` };
    }
  }
  return NO_MATCH;
}

/** Rule descriptions for the "what this checks" list, in evaluation order. */
export const RULE_SUMMARY: readonly { label: string; verdict: SimulatedVerdict }[] =
  RULES.map((r) => ({ label: r.label, verdict: r.decision.verdict }));
