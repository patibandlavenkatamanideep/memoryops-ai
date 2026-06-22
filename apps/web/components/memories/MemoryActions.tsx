"use client";

import { useState } from "react";
import { MemoryRecord, api } from "@/lib/api";

// Every button maps 1:1 to an audited backend action (PATCH / DELETE).
// Deleted memories expose no actions — they can never be reactivated.
export default function MemoryActions({
  memory,
  onChanged,
  layout = "inline",
}: {
  memory: MemoryRecord;
  onChanged: () => void | Promise<void>;
  layout?: "inline" | "stacked";
}) {
  const [busy, setBusy] = useState(false);

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
      {memory.status === "pending" && (
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
      {memory.status === "archived" ? (
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
      )}
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
    </div>
  );
}
