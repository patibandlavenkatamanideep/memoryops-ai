"use client";

import Link from "next/link";
import { MemoryRecord } from "@/lib/api";
import MemoryActions from "@/components/memories/MemoryActions";

// Human-in-the-loop approval queue: memories the policy broker routed to
// PENDING_APPROVAL. Approve → active, reject → rejected. Both are audited.
export default function PendingMemoryQueue({
  rows,
  onChanged,
}: {
  rows: MemoryRecord[];
  onChanged: () => void | Promise<void>;
}) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        Nothing awaiting approval. Sensitive or low-confidence captures land here.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      {rows.map((m) => (
        <article key={m.id} className="card space-y-3">
          <div className="flex items-start justify-between gap-3">
            <Link href={`/memories/${m.id}`} className="text-slate-100 hover:underline">
              {m.content}
            </Link>
            <MemoryActions memory={m} onChanged={onChanged} layout="stacked" />
          </div>
          <div className="flex flex-wrap gap-1 text-xs">
            <span className="chip">{m.memory_type}</span>
            <span className="chip">sensitivity: {m.sensitivity}</span>
            <span className="chip">importance {m.importance}</span>
            <span className="chip">confidence {m.confidence.toFixed(2)}</span>
            <span className="chip" title={m.source.excerpt}>
              source: {m.source.kind}
            </span>
          </div>
        </article>
      ))}
    </div>
  );
}
