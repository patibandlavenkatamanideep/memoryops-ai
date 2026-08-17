"use client";

import Link from "next/link";

import { MemoryRecord } from "@/lib/api";
import MemoryActions from "@/components/memories/MemoryActions";
import { Badge, EmptyState, Panel, PanelBody } from "@/components/ui";

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
      <EmptyState
        title="Nothing awaiting approval"
        description="Sensitive or low-confidence captures land here instead of being stored. An empty queue means the broker admitted or refused every candidate outright."
      />
    );
  }

  return (
    <div className="space-y-3">
      {rows.map((m) => (
        <Panel key={m.id} as="article" tone="warn">
          <PanelBody className="space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <Link
                href={`/memories/${m.id}`}
                className="min-w-0 break-words rounded-sm text-sm leading-relaxed text-fg underline-offset-4 hover:text-accent-strong hover:underline"
              >
                {m.content}
              </Link>
              <MemoryActions memory={m} onChanged={onChanged} />
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge tone="quiet">{m.memory_type}</Badge>
              <Badge tone="quiet">sensitivity: {m.sensitivity}</Badge>
              <Badge tone="quiet">importance {m.importance}</Badge>
              <Badge tone="quiet">confidence {m.confidence.toFixed(2)}</Badge>
              <Badge tone="quiet" title={m.source.excerpt}>
                source: {m.source.kind}
              </Badge>
            </div>
          </PanelBody>
        </Panel>
      ))}
    </div>
  );
}
