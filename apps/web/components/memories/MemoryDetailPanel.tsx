"use client";

import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  AuditEvent,
  MemoryProvenance as Provenance,
  MemoryRecord,
  api,
} from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  LoadingState,
  MonoId,
  Panel,
  PanelBody,
  PanelHeader,
  StatusBadge,
  TextArea,
  Field,
} from "@/components/ui";
import AuditTimeline from "@/components/audit/AuditTimeline";
import MemoryActions from "./MemoryActions";
import MemoryProvenance from "./MemoryProvenance";

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
      setError(
        e instanceof ApiError
          ? `The API returned ${e.status} for this memory.`
          : e instanceof Error
            ? e.message
            : String(e),
      );
    } finally {
      setLoading(false);
    }
  }, [memoryId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !memory) return <LoadingState label="Loading memory…" rows={4} />;
  if (error) {
    return (
      <ErrorState
        detail={error}
        action={
          <Button size="sm" onClick={() => void load()}>
            Retry
          </Button>
        }
      />
    );
  }
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
    <div className="space-y-4">
      <Panel>
        {/* The heading is the word "Memory": lifecycle badges belong in the body, not
            inside an <h2>, where they would make the document outline read
            "active preference sensitivity: low". */}
        <PanelHeader
          title="Memory"
          description={<MonoId value={memory.id} chars={36} label="id" />}
          actions={<MemoryActions memory={memory} onChanged={load} />}
        />
        <PanelBody className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={memory.status} />
            <Badge tone="quiet">{memory.memory_type}</Badge>
            <Badge tone="quiet">sensitivity: {memory.sensitivity}</Badge>
          </div>
          {editing ? (
            <div className="space-y-3">
              <Field label="Memory content">
                <TextArea
                  rows={4}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  disabled={saving}
                />
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" size="sm" disabled={saving} onClick={saveEdit}>
                  {saving ? "Saving…" : "Save"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={saving}
                  onClick={() => {
                    setDraft(memory.content);
                    setEditing(false);
                  }}
                >
                  Cancel
                </Button>
              </div>
              <p className="text-xs text-fg-muted">
                Editing content is an audited lifecycle mutation; the revision is recorded
                on the timeline below.
              </p>
            </div>
          ) : (
            <div className="flex flex-wrap items-start justify-between gap-3">
              <p className="min-w-0 whitespace-pre-wrap break-words text-sm leading-relaxed text-fg">
                {memory.content}
              </p>
              {memory.status !== "deleted" ? (
                <Button size="sm" onClick={() => setEditing(true)}>
                  Edit
                </Button>
              ) : null}
            </div>
          )}
        </PanelBody>
      </Panel>

      <MemoryProvenance provenance={provenance} />

      <Panel>
        <PanelHeader
          title="Audit timeline"
          description="Append-only history for this memory."
        />
        <PanelBody>
          <AuditTimeline events={events} emptyLabel="No audit events for this memory." />
        </PanelBody>
      </Panel>
    </div>
  );
}
