"use client";

import { useState } from "react";

import { MemoryRecord, api } from "@/lib/api";
import type { UiCapabilities } from "@/lib/capabilities";
import { Button, cn } from "@/components/ui";

// Every button maps 1:1 to an audited backend action (PATCH / DELETE).
// Deleted memories expose no actions — they can never be reactivated.
export default function MemoryActions({
  memory,
  onChanged,
  layout = "inline",
  capabilities,
}: {
  memory: MemoryRecord;
  onChanged: () => void | Promise<void>;
  layout?: "inline" | "stacked";
  /**
   * What this persona may attempt, from `uiCapabilities()` — the same contract the
   * proxy enforces with. Omitted means "show everything and let the server decide",
   * which is the pre-existing behaviour and still safe: hiding a control is a
   * usability decision, and both the BFF and the API refuse independently.
   */
  capabilities?: UiCapabilities;
}) {
  const [busy, setBusy] = useState(false);

  const may = {
    approveOrReject: capabilities?.canApproveOrReject ?? true,
    archiveOrRestore: capabilities?.canArchiveOrRestore ?? true,
    delete: capabilities?.canDeleteMemory ?? true,
  };

  if (memory.status === "deleted") {
    return <span className="text-xs text-fg-muted">deleted — no actions</span>;
  }

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className={cn(
        "flex gap-2",
        layout === "stacked" ? "flex-col items-start" : "flex-wrap items-center",
      )}
    >
      {memory.status === "pending" && may.approveOrReject ? (
        <>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => run(() => api.patchMemory(memory.id, { status: "active" }))}
          >
            Approve
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => run(() => api.patchMemory(memory.id, { status: "rejected" }))}
          >
            Reject
          </Button>
        </>
      ) : null}

      {may.archiveOrRestore ? (
        memory.status === "archived" ? (
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => run(() => api.patchMemory(memory.id, { status: "active" }))}
          >
            Restore
          </Button>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => run(() => api.patchMemory(memory.id, { status: "archived" }))}
          >
            Archive
          </Button>
        )
      ) : null}

      {may.delete ? (
        <Button
          size="sm"
          variant="danger"
          disabled={busy}
          onClick={() => {
            // Soft delete is a governed, audited state change that permanently removes
            // the memory from every future retrieval. It is not an undo, so it is
            // confirmed rather than fired on a single click.
            if (
              window.confirm(
                `Soft-delete this memory?\n\n"${memory.content}"\n\nIt will be excluded from all future retrieval and cannot be restored.`,
              )
            ) {
              void run(() => api.deleteMemory(memory.id));
            }
          }}
        >
          Delete
        </Button>
      ) : null}
    </div>
  );
}
