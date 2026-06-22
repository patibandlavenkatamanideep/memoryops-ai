"use client";

import { useEffect, useState } from "react";
import { AuditEvent, api } from "@/lib/api";
import AuditTimeline from "@/components/audit/AuditTimeline";

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setEvents(await api.audit());
        setError("");
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Audit log</h1>
        <p className="mt-1 text-sm text-slate-400">
          Append-only lifecycle history across all memories (tenant-scoped), newest first.
        </p>
      </div>
      {error && <p className="text-sm text-rose-400">API error: {error}</p>}
      {loading && <p className="text-sm text-slate-400">Loading…</p>}
      <section className="card">
        <AuditTimeline events={events} />
      </section>
    </div>
  );
}
