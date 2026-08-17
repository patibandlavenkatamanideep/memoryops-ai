"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, AuditEvent, MemoryRecord, api } from "@/lib/api";
import PendingMemoryQueue from "@/components/governance/PendingMemoryQueue";
import PolicyDecisionCard, {
  POLICY_ACTIONS,
} from "@/components/governance/PolicyDecisionCard";
import {
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  SectionHeader,
} from "@/components/ui";

export default function GovernancePage() {
  const [pending, setPending] = useState<MemoryRecord[]>([]);
  const [decisions, setDecisions] = useState<AuditEvent[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [pendingRows, audit] = await Promise.all([
        api.memories({ status: "pending" }),
        api.audit(),
      ]);
      setPending(pendingRows);
      setDecisions(audit.filter((e) => POLICY_ACTIONS.includes(e.action)).slice(0, 30));
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
    <div className="space-y-8">
      <PageHeader
        eyebrow="Governance"
        title="Governance"
        description="Human-in-the-loop approvals and the policy broker's recorded decisions. The broker runs before any write and stays authoritative — this surface shows what it decided, and lets an operator resolve what it deferred."
        actions={
          <Button size="sm" onClick={() => void load()} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </Button>
        }
      />

      {error ? (
        <ErrorState
          title="Could not load governance state"
          detail={error}
          action={
            <Button size="sm" onClick={() => void load()}>
              Retry
            </Button>
          }
        />
      ) : null}

      {loading && pending.length === 0 && decisions.length === 0 ? (
        <LoadingState label="Loading governance state…" rows={5} />
      ) : null}

      <section className="space-y-3">
        <SectionHeader
          title="Approval queue"
          count={`${pending.length} pending`}
          description="Candidates the broker routed to PENDING_APPROVAL rather than storing. Approving or rejecting is an audited lifecycle mutation."
        />
        <PendingMemoryQueue rows={pending} onChanged={load} />
      </section>

      <section className="space-y-3">
        <SectionHeader
          title="Recent policy decisions"
          count={decisions.length > 0 ? `${decisions.length} shown` : undefined}
          description="Policy verdicts drawn from the append-only audit log — saved, deferred, blocked, dropped or merged."
        />
        {decisions.length === 0 ? (
          <EmptyState
            title="No policy decisions recorded yet"
            description="The broker records a verdict for every candidate memory. Start a chat session to produce the first one."
          />
        ) : (
          <div className="grid gap-3 xl:grid-cols-2">
            {decisions.map((e) => (
              <PolicyDecisionCard key={e.id} event={e} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
