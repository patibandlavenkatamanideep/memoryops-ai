"use client";

import Link from "next/link";

import { AuditEvent } from "@/lib/api";
import {
  Badge,
  MonoId,
  Panel,
  PanelBody,
  type Tone,
} from "@/components/ui";

// The policy broker records its decision as an audit event (invariant #5/#7):
// memory_pending_approval, memory_blocked, memory_dropped, memory_created, etc.
// This card renders one such decision with its rationale — the broker stays
// authoritative; the UI only displays what it decided.
const DECISION_META: Record<string, { label: string; tone: Tone }> = {
  memory_created: { label: "SAVED", tone: "ok" },
  memory_pending_approval: { label: "PENDING APPROVAL", tone: "warn" },
  memory_blocked: { label: "BLOCKED", tone: "danger" },
  memory_dropped: { label: "DROPPED (low utility)", tone: "quiet" },
  memory_updated: { label: "UPDATED EXISTING", tone: "info" },
  memory_merged: { label: "MERGED", tone: "info" },
};

export const POLICY_ACTIONS = Object.keys(DECISION_META);

/** Panel tone follows the verdict, so a wall of decisions is scannable by outcome. */
const PANEL_TONE: Partial<Record<Tone, "default" | "ok" | "warn" | "danger">> = {
  ok: "ok",
  warn: "warn",
  danger: "danger",
};

export default function PolicyDecisionCard({ event }: { event: AuditEvent }) {
  const meta = DECISION_META[event.action] ?? { label: event.action, tone: "neutral" as Tone };
  const md = event.metadata ?? {};

  return (
    <Panel as="article" tone={PANEL_TONE[meta.tone] ?? "default"}>
      <PanelBody className="space-y-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Badge tone={meta.tone}>{meta.label}</Badge>
          <span className="text-xs text-fg-muted">
            {new Date(event.created_at).toLocaleString()}
          </span>
        </div>

        <p className="break-words text-sm leading-relaxed text-fg-secondary">
          {event.reason}
        </p>

        <div className="flex flex-wrap items-center gap-2">
          {typeof md.type === "string" ? <Badge tone="quiet">{md.type}</Badge> : null}
          {typeof md.sensitivity === "string" ? (
            <Badge tone="quiet">sensitivity: {md.sensitivity}</Badge>
          ) : null}
          {event.trace_id ? <MonoId label="trace" value={event.trace_id} chars={10} /> : null}
          {event.memory_id ? (
            <Link
              href={`/memories/${event.memory_id}`}
              className="ml-auto rounded-sm text-xs text-accent-strong underline-offset-4 hover:underline"
            >
              View memory →
            </Link>
          ) : null}
        </div>
      </PanelBody>
    </Panel>
  );
}
