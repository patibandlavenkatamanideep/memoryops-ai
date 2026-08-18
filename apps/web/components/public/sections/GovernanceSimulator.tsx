"use client";

import { useState } from "react";

import { Badge, Button, Field, TextInput, type Tone } from "@/components/ui";
import { IllustrativeBlock } from "../Illustrative";
import { Section, SectionIntro } from "../PublicShell";
import {
  EXAMPLE_CANDIDATES,
  RULE_SUMMARY,
  SIMPLIFICATIONS,
  simulate,
  type SimulatedVerdict,
} from "./simulate";

/**
 * Client-side policy illustration.
 *
 * Interactive because the point is felt rather than read: type a candidate, watch a
 * verdict come back with a reason. It calls nothing — the whole rule set is in
 * `simulate.ts` and runs in the browser.
 *
 * The rules it checks are listed on screen, and so is what it leaves out. A visitor
 * should finish this section knowing they saw a simplification, which is why the
 * simplifications are rendered next to the control rather than buried under it.
 */

const VERDICT_TONE: Record<SimulatedVerdict, Tone> = {
  SAVE: "ok",
  BLOCK: "danger",
  "SESSION ONLY": "info",
  REVIEW: "warn",
  "NO MATCH": "quiet",
};

export default function GovernanceSimulator() {
  const [candidate, setCandidate] = useState(EXAMPLE_CANDIDATES[0]);
  const decision = simulate(candidate);

  return (
    <Section id="simulator">
      <SectionIntro eyebrow="Policy" title="Try a policy decision">
        Different candidates deserve different outcomes. Not everything worth saying
        is worth remembering, and some of it must never be stored at all.
      </SectionIntro>

      <IllustrativeBlock
        kind="Simulation"
        note="A simplified illustration running entirely in your browser. It calls no MemoryOps API, stores nothing, and is not the policy broker — the real broker runs server-side and considers far more than the patterns below."
      >
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
          <div className="space-y-4">
            <div className="space-y-2">
              <p className="text-label uppercase text-fg-muted">Example candidates</p>
              <div className="flex flex-wrap gap-2">
                {EXAMPLE_CANDIDATES.map((example, i) => (
                  <Button
                    key={example}
                    size="sm"
                    variant={example === candidate ? "primary" : "secondary"}
                    onClick={() => setCandidate(example)}
                    className="max-w-full"
                  >
                    <span className="truncate">Example {i + 1}</span>
                  </Button>
                ))}
              </div>
            </div>

            <Field
              label="Candidate memory"
              hint="Edit it, or write your own. Nothing you type leaves the page."
            >
              <TextInput
                value={candidate}
                onChange={(e) => setCandidate(e.target.value)}
                placeholder="e.g. I prefer short answers with no emojis."
              />
            </Field>

            <div
              // Announced so a screen-reader user hears the verdict change as they
              // type, rather than having to hunt for what moved.
              role="status"
              aria-live="polite"
              className="min-h-[9rem] rounded-lg border border-line bg-surface p-4"
            >
              {decision === null ? (
                <p className="text-sm text-fg-muted">
                  Enter a candidate memory to see an illustrative verdict.
                </p>
              ) : (
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={VERDICT_TONE[decision.verdict]}>
                      {decision.verdict}
                    </Badge>
                    <span className="font-mono text-xs text-fg-muted">
                      {decision.rule}
                    </span>
                  </div>
                  <p className="text-sm leading-relaxed text-fg-secondary">
                    {decision.rationale}
                  </p>
                  <p className="border-t border-line pt-3 text-xs text-fg-muted">
                    <span className="text-fg-secondary">Outcome:</span>{" "}
                    {decision.outcome}
                  </p>
                </div>
              )}
            </div>
          </div>

          <div className="space-y-5">
            <div className="space-y-2">
              <p className="text-label uppercase text-fg-muted">
                What this illustration checks
              </p>
              <ol className="space-y-1.5">
                {RULE_SUMMARY.map((rule, i) => (
                  <li
                    key={rule.label}
                    className="flex items-start gap-2 text-xs leading-relaxed text-fg-secondary"
                  >
                    <span aria-hidden className="font-mono text-fg-muted">
                      {i + 1}.
                    </span>
                    <span className="min-w-0">
                      {rule.label}
                      <span className="text-fg-muted"> → {rule.verdict}</span>
                    </span>
                  </li>
                ))}
              </ol>
            </div>

            <div className="space-y-2">
              <p className="text-label uppercase text-fg-muted">
                What it does not model
              </p>
              <ul className="space-y-1.5">
                {SIMPLIFICATIONS.map((item) => (
                  <li
                    key={item}
                    className="flex gap-2 text-xs leading-relaxed text-fg-muted"
                  >
                    <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-line-strong" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </IllustrativeBlock>
    </Section>
  );
}
