"use client";

import { useState } from "react";
import { MemoryRecord, api } from "@/lib/api";
import type { UiCapabilities } from "@/lib/capabilities";

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
    return <span className="text-xs text-slate-600">deleted — no actions</span>;
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

  const wrap =
    layout === "stacked"
      ? "flex flex-col items-start gap-2"
      : "space-x-3 whitespace-nowrap";

  return (
    <div className={wrap}>
      {memory.status === "pending" && may.approveOrReject && (
        <>
          <button
            className="text-emerald-400 hover:underline disabled:opacity-40"
            disabled={busy}
            onClick={() => run(() => api.patchMemory(memory.id, { status: "active" }))}
          >
            approve
          </button>
          <button
            className="text-rose-400 hover:underline disabled:opacity-40"
            disabled={busy}
            onClick={() => run(() => api.patchMemory(memory.id, { status: "rejected" }))}
          >
            reject
          </button>
        </>
      )}
      {may.archiveOrRestore &&
        (memory.status === "archived" ? (
        <button
          className="text-emerald-400 hover:underline disabled:opacity-40"
          disabled={busy}
          onClick={() => run(() => api.patchMemory(memory.id, { status: "active" }))}
        >
          restore
        </button>
      ) : (
        <button
          className="text-slate-400 hover:underline disabled:opacity-40"
          disabled={busy}
          onClick={() => run(() => api.patchMemory(memory.id, { status: "archived" }))}
        >
          archive
        </button>
        ))}
      {may.delete && (
      <button
        className="text-rose-400 hover:underline disabled:opacity-40"
        disabled={busy}
        onClick={() => {
          if (
            confirm(
              "Soft-delete this memory? It will be excluded from all future retrieval."
            )
          ) {
            run(() => api.deleteMemory(memory.id));
          }
        }}
      >
        delete
      </button>
      )}
    </div>
  );
}
