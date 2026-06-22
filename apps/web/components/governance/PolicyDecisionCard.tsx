"use client";

import Link from "next/link";
import { AuditEvent } from "@/lib/api";

// The policy broker records its decision as an audit event (invariant #5/#7):
// memory_pending_approval, memory_blocked, memory_dropped, memory_created, etc.
// This card renders one such decision with its rationale — the broker stays
// authoritative; the UI only displays what it decided.
const DECISION_META: Record<string, { label: string; cls: string }> = {
  memory_created: { label: "SAVED", cls: "border-emerald-700 text-emerald-300" },
  memory_pending_approval: { label: "PENDING APPROVAL", cls: "border-amber-700 text-amber-300" },
  memory_blocked: { label: "BLOCKED", cls: "border-rose-800 text-rose-300" },
  memory_dropped: { label: "DROPPED (low utility)", cls: "border-slate-600 text-slate-400" },
  memory_updated: { label: "UPDATED EXISTING", cls: "border-sky-700 text-sky-300" },
  memory_merged: { label: "MERGED", cls: "border-sky-700 text-sky-300" },
};

export const POLICY_ACTIONS = Object.keys(DECISION_META);

export default function PolicyDecisionCard({ event }: { event: AuditEvent }) {
  const meta = DECISION_META[event.action] ?? {
    label: event.action,
    cls: "border-slate-700 text-slate-300",
  };
  const md = event.metadata ?? {};
  return (
    <article className="card space-y-2">
      <div className="flex items-center justify-between gap-3">
        <span className={`chip ${meta.cls}`}>{meta.label}</span>
        <span className="text-xs text-slate-500">
          {new Date(event.created_at).toLocaleString()}
        </span>
      </div>
      <p className="text-sm text-slate-300">{event.reason}</p>
      <div className="flex flex-wrap gap-1 text-xs">
        {typeof md.type === "string" && <span className="chip">{md.type}</span>}
        {typeof md.sensitivity === "string" && (
          <span className="chip">sensitivity: {md.sensitivity}</span>
        )}
        {event.memory_id && (
          <Link href={`/memories/${event.memory_id}`} className="chip hover:text-white">
            view memory
          </Link>
        )}
      </div>
    </article>
  );
}
