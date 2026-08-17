"use client";

import type { ChatResponse, Decision } from "@/lib/api";
import {
  Badge,
  Disclosure,
  FieldLabel,
  MonoId,
  Panel,
  PanelBody,
  ScoreBar,
  type Tone,
} from "@/components/ui";

/**
 * One governed turn: what the user said, what the assistant answered, and every
 * governance decision the runtime made in between.
 *
 * Everything rendered here comes from the `ChatResponse` the API returned. Nothing is
 * derived, inferred or filled in — if the response omits a block (no candidates, no
 * retrieval mode, temporary chat), that block is absent rather than defaulted, because
 * a governance surface that guesses is worse than one that says nothing.
 */

/** Policy broker verdict → tone. Unknown verdicts stay neutral, never "saved". */
const DECISION_TONE: Record<Decision, Tone> = {
  SAVE: "ok",
  UPDATE_EXISTING: "ok",
  MERGE_WITH_EXISTING: "ok",
  PENDING_APPROVAL: "warn",
  BLOCK: "danger",
  DROP_LOW_UTILITY: "quiet",
};

const RETRIEVAL_MODE_TONE: Record<string, Tone> = {
  hybrid: "accent",
  fallback: "warn",
  none: "quiet",
};

const RETRIEVAL_MODE_HINT: Record<string, string> = {
  hybrid: "vector + keyword",
  fallback: "keyword only — embedding lookup degraded",
  none: "memory bypassed for this turn",
};

const LOOP_STATUS_TONE: Record<string, Tone> = {
  completed: "ok",
  safe_degraded: "warn",
  failed: "danger",
};

export default function ChatTurn({
  userMessage,
  response,
}: {
  userMessage: string;
  response: ChatResponse;
}) {
  const {
    assistant_message,
    used_memories,
    candidate_memories,
    temporary_chat,
    retrieval_mode,
    loop_evidence,
    trace_id,
  } = response;

  return (
    <Panel as="article">
      <PanelBody className="space-y-5">
        <div className="space-y-3">
          <div className="space-y-1">
            <FieldLabel>You</FieldLabel>
            <p className="whitespace-pre-wrap break-words text-sm text-fg-secondary">
              {userMessage}
            </p>
          </div>
          <div className="space-y-1">
            <FieldLabel>Assistant</FieldLabel>
            <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-fg">
              {assistant_message}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {temporary_chat ? (
            <Badge tone="warn">temporary — nothing written or read</Badge>
          ) : null}

          {!temporary_chat && retrieval_mode ? (
            <Badge
              tone={RETRIEVAL_MODE_TONE[retrieval_mode] ?? "neutral"}
              title={RETRIEVAL_MODE_HINT[retrieval_mode]}
            >
              retrieval: {retrieval_mode}
            </Badge>
          ) : null}

          {loop_evidence
            ? Object.entries(loop_evidence).map(([loop, status]) => (
                <Badge key={loop} tone={LOOP_STATUS_TONE[status] ?? "neutral"}>
                  {loop.replace(/_/g, " ")}: {status}
                </Badge>
              ))
            : null}

          <MonoId label="trace" value={trace_id} chars={10} className="ml-auto" />
        </div>

        {candidate_memories.length > 0 ? (
          <section className="space-y-2">
            <FieldLabel>Policy decisions ({candidate_memories.length})</FieldLabel>
            <ul className="space-y-2">
              {candidate_memories.map((candidate, index) => (
                <li
                  key={`${candidate.content}-${index}`}
                  className="rounded-lg border border-line bg-surface-raised p-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={DECISION_TONE[candidate.decision] ?? "neutral"}>
                      {candidate.decision}
                    </Badge>
                    <Badge tone="quiet">{candidate.type}</Badge>
                    <Badge tone="quiet">sensitivity: {candidate.sensitivity}</Badge>
                  </div>
                  <p className="mt-2 break-words text-sm text-fg">{candidate.content}</p>
                  <p className="mt-1 text-xs leading-relaxed text-fg-muted">
                    {candidate.reason}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {used_memories.length > 0 ? (
          <section className="space-y-2">
            <FieldLabel>Memory used ({used_memories.length})</FieldLabel>
            <ul className="space-y-2">
              {used_memories.map((memory) => (
                <li
                  key={memory.memory_id}
                  className="space-y-2 rounded-lg border border-line bg-surface-raised p-3"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <p className="min-w-0 break-words text-sm text-fg">{memory.content}</p>
                    <Badge tone="accent" className="shrink-0">
                      {memory.memory_type ?? "memory"} · {memory.score.toFixed(2)}
                    </Badge>
                  </div>
                  {memory.source?.kind ? (
                    <p className="text-xs text-fg-muted">source: {memory.source.kind}</p>
                  ) : null}
                  {memory.score_breakdown ? (
                    <Disclosure summary="Why this ranked">
                      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                        {Object.entries(memory.score_breakdown).map(([signal, value]) => (
                          <ScoreBar
                            key={signal}
                            label={signal.replace(/_/g, " ")}
                            value={Number(value)}
                          />
                        ))}
                      </div>
                    </Disclosure>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </PanelBody>
    </Panel>
  );
}
