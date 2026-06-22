"use client";

import { AuditEvent } from "@/lib/api";

// Append-only lifecycle history (invariant #7), newest first.
const ACTION_DOT: Record<string, string> = {
  memory_created: "bg-emerald-400",
  memory_approved: "bg-emerald-400",
  memory_pending_approval: "bg-amber-400",
  memory_updated: "bg-sky-400",
  memory_merged: "bg-sky-400",
  memory_archived: "bg-slate-400",
  memory_rejected: "bg-rose-400",
  memory_blocked: "bg-rose-400",
  memory_dropped: "bg-rose-400",
  memory_deleted: "bg-rose-500",
  memory_viewed: "bg-slate-600",
};

export default function AuditTimeline({
  events,
  emptyLabel = "No audit events yet.",
}: {
  events: AuditEvent[];
  emptyLabel?: string;
}) {
  if (events.length === 0) {
    return <p className="text-sm text-slate-500">{emptyLabel}</p>;
  }
  return (
    <ol className="space-y-3">
      {events.map((e) => (
        <li key={e.id} className="flex gap-3">
          <span
            className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
              ACTION_DOT[e.action] ?? "bg-slate-500"
            }`}
          />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-slate-200">{e.action}</span>
              <span className="text-xs text-slate-500">
                {new Date(e.created_at).toLocaleString()}
              </span>
            </div>
            <p className="text-sm text-slate-400">{e.reason}</p>
            {e.memory_id && (
              <p className="font-mono text-[10px] text-slate-600">
                memory {e.memory_id.slice(0, 8)}
                {e.trace_id ? ` · trace ${e.trace_id}` : ""}
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
