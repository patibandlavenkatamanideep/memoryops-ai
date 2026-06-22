"use client";

import { useCallback, useEffect, useState } from "react";
import { AuditEvent, MemoryRecord, api } from "@/lib/api";
import PendingMemoryQueue from "@/components/governance/PendingMemoryQueue";
import PolicyDecisionCard, {
  POLICY_ACTIONS,
} from "@/components/governance/PolicyDecisionCard";

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
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Governance</h1>
        <p className="mt-1 text-sm text-slate-400">
          Human-in-the-loop approvals and the policy broker&apos;s recorded decisions.
        </p>
      </div>
      {error && <p className="text-sm text-rose-400">API error: {error}</p>}
      {loading && <p className="text-sm text-slate-400">Loading…</p>}

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-white">
          Approval queue
          <span className="ml-2 text-sm font-normal text-slate-500">
            {pending.length} pending
          </span>
        </h2>
        <PendingMemoryQueue rows={pending} onChanged={load} />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-white">Recent policy decisions</h2>
        {decisions.length === 0 ? (
          <p className="text-sm text-slate-500">No policy decisions recorded yet.</p>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {decisions.map((e) => (
              <PolicyDecisionCard key={e.id} event={e} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
