"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, AuditEvent, api } from "@/lib/api";
import AuditTimeline from "@/components/audit/AuditTimeline";
import {
  Button,
  ErrorState,
  LoadingState,
  PageHeader,
  Panel,
  PanelBody,
} from "@/components/ui";

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setEvents(await api.audit());
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? `The API returned ${e.status}.` : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Governance"
        title="Audit"
        description="Append-only lifecycle evidence for this tenant, newest first. Every mutation and its audit event commit in the same transaction, so this record cannot diverge from what actually happened."
        actions={
          <Button size="sm" onClick={() => void load()} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </Button>
        }
      />

      {error ? (
        <ErrorState
          title="Could not load the audit log"
          detail={error}
          action={
            <Button size="sm" onClick={() => void load()}>
              Retry
            </Button>
          }
        />
      ) : null}

      {loading && events.length === 0 ? (
        <LoadingState label="Loading audit events…" rows={6} />
      ) : !error ? (
        <Panel>
          <PanelBody>
            <AuditTimeline events={events} />
          </PanelBody>
        </Panel>
      ) : null}
    </div>
  );
}
