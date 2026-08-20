"use client";

import Link from "next/link";

import { AuditEvent } from "@/lib/api";
import {
  Badge,
  EmptyState,
  MonoId,
  Timeline,
  TimelineItem,
  type Tone,
} from "@/components/ui";

/**
 * Append-only lifecycle history (invariant #7), newest first.
 *
 * Tone comes from what the event *is*, so the timeline can be read as governance
 * rather than as a log: writes and approvals read as allowed, blocks and deletions as
 * denied or destructive. An action this UI has not been taught about renders neutral —
 * never as a success.
 */
const ACTION_TONE: Record<string, Tone> = {
  memory_created: "ok",
  memory_approved: "ok",
  memory_updated: "info",
  memory_merged: "info",
  memory_pending_approval: "warn",
  memory_archived: "neutral",
  memory_rejected: "danger",
  memory_blocked: "danger",
  memory_dropped: "danger",
  memory_deleted: "danger",
  memory_viewed: "quiet",
  memory_retrieved: "quiet",
};

export default function AuditTimeline({
  events,
  emptyLabel = "No audit events yet.",
}: {
  events: AuditEvent[];
  emptyLabel?: string;
}) {
  if (events.length === 0) {
    return (
      <EmptyState
        title={emptyLabel}
        description="Every lifecycle mutation commits together with its audit event, so this fills as memory is captured, governed and forgotten."
      />
    );
  }

  return (
    <Timeline>
      {events.map((e) => (
        <TimelineItem
          key={e.id}
          tone={ACTION_TONE[e.action] ?? "neutral"}
          title={<span className="font-mono text-xs">{e.action}</span>}
          timestamp={new Date(e.created_at).toLocaleString()}
          description={e.reason}
          meta={
            <>
              {e.memory_id ? (
                <Link
                  href={`/memories/${e.memory_id}`}
                  className="inline-flex min-h-[2rem] items-center rounded-sm underline-offset-4 hover:underline"
                >
                  <MonoId label="memory" value={e.memory_id} chars={10} />
                </Link>
              ) : null}
              {e.trace_id ? <MonoId label="trace" value={e.trace_id} chars={10} /> : null}
              {e.user_id ? <Badge tone="quiet">{e.user_id}</Badge> : null}
            </>
          }
        />
      ))}
    </Timeline>
  );
}
