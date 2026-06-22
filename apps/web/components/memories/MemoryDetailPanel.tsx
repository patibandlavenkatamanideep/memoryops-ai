"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AuditEvent,
  MemoryProvenance as Provenance,
  MemoryRecord,
  api,
} from "@/lib/api";
import { statusClass } from "./statusStyles";
import MemoryActions from "./MemoryActions";
import MemoryProvenance from "./MemoryProvenance";
import AuditTimeline from "@/components/audit/AuditTimeline";

// Full control-plane view for one memory: content (editable), lifecycle
// actions, provenance/explainability, and the per-memory audit timeline.
export default function MemoryDetailPanel({ memoryId }: { memoryId: string }) {
  const [memory, setMemory] = useState<MemoryRecord | null>(null);
  const [provenance, setProvenance] = useState<Provenance | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [m, prov, audit] = await Promise.all([
        api.memory(memoryId),
        api.memoryProvenance(memoryId),
        api.memoryAudit(memoryId),
      ]);
      setMemory(m);
      setProvenance(prov);
      setEvents(audit);
      setDraft(m.content);
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [memoryId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !memory) return <p className="text-sm text-slate-400">Loading…</p>;
  if (error) return <p className="text-sm text-rose-400">API error: {error}</p>;
  if (!memory) return null;

  async function saveEdit() {
    if (!memory) return;
    setSaving(true);
    try {
      await api.patchMemory(memory.id, { content: draft });
      setEditing(false);
      await load();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="card space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`chip ${statusClass(memory.status)}`}>{memory.status}</span>
              <span className="chip">{memory.memory_type}</span>
              <span className="chip">sensitivity: {memory.sensitivity}</span>
            </div>
            <p className="font-mono text-xs text-slate-600">{memory.id}</p>
          </div>
          <MemoryActions memory={memory} onChanged={load} layout="stacked" />
        </div>

        {editing ? (
          <div className="space-y-2">
            <textarea
              className="w-full rounded-lg border border-slate-700 bg-ink p-3 text-sm"
              rows={4}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <div className="flex gap-3 text-sm">
              <button className="btn" disabled={saving} onClick={saveEdit}>
                {saving ? "Saving…" : "Save"}
              </button>
              <button
                className="text-slate-400 hover:text-white"
                onClick={() => {
                  setDraft(memory.content);
                  setEditing(false);
                }}
              >
                cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="flex items-start justify-between gap-3">
            <p className="text-slate-100">{memory.content}</p>
            {memory.status !== "deleted" && (
              <button
                className="shrink-0 text-sm text-accent hover:underline"
                onClick={() => setEditing(true)}
              >
                edit
              </button>
            )}
          </div>
        )}
      </section>

      <MemoryProvenance provenance={provenance} />

      <section className="card space-y-3">
        <h3 className="font-semibold text-white">Audit timeline</h3>
        <AuditTimeline events={events} emptyLabel="No audit events for this memory." />
      </section>
    </div>
  );
}
