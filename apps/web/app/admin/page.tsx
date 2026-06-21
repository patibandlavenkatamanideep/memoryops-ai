"use client";

import { useEffect, useState } from "react";
import { api, AuditEvent } from "@/lib/api";

type Metrics = Awaited<ReturnType<typeof api.metrics>>;
type Ready = Awaited<ReturnType<typeof api.ready>>;

export default function AdminPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [ready, setReady] = useState<Ready | null>(null);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [evals, setEvals] = useState<{ passed: number; total: number; pass_rate: number } | null>(
    null
  );
  const [error, setError] = useState("");

  async function load() {
    try {
      const [m, a, r] = await Promise.all([api.metrics(), api.audit(), api.ready()]);
      setMetrics(m);
      setAudit(a);
      setReady(r);
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  const cards = metrics
    ? [
        { label: "Total memories", value: metrics.total_memories },
        { label: "Active", value: metrics.by_status.active ?? 0 },
        { label: "Pending", value: metrics.by_status.pending ?? 0 },
        { label: "Blocked", value: metrics.by_action.memory_blocked ?? 0 },
        { label: "Deleted", value: metrics.by_status.deleted ?? 0 },
        { label: "Retrievals", value: metrics.by_action.memory_retrieved ?? 0 },
        { label: "Audit events", value: metrics.audit_events },
      ]
    : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Admin & audit</h1>
        <button
          className="btn"
          onClick={async () => setEvals(await api.runEvals())}
        >
          Run evals
        </button>
      </div>
      {error && <p className="text-sm text-rose-400">API error: {error}</p>}

      {evals && (
        <div className="card space-y-2">
          <span className="chip border-emerald-600 text-emerald-400">
            evals {evals.passed}/{evals.total} passed · {(evals.pass_rate * 100).toFixed(0)}%
          </span>
          {evals.loop_engineering && (
            <div className="flex flex-wrap gap-2">
              {Object.entries(evals.loop_engineering).map(([loop, status]) => (
                <span key={loop} className="chip">
                  {loop.replace(/_/g, " ")}: {status}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {cards.map((c) => (
          <div key={c.label} className="card">
            <p className="text-xs uppercase tracking-wide text-slate-500">{c.label}</p>
            <p className="mt-1 text-2xl font-bold text-white">{c.value}</p>
          </div>
        ))}
      </div>

      <div className="card space-y-3">
        <h2 className="font-semibold text-white">Retrieval & data layer</h2>
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <div className="card">
            <p className="text-xs uppercase tracking-wide text-slate-500">Embedding provider</p>
            <p className="mt-1 text-lg font-bold text-white">
              {ready?.embeddings_provider ?? "—"}
              <span className="ml-1 text-sm font-normal text-slate-500">
                {ready ? `· ${ready.embedding_dim}d` : ""}
              </span>
            </p>
          </div>
          <div className="card">
            <p className="text-xs uppercase tracking-wide text-slate-500">Storage</p>
            <p className="mt-1 text-lg font-bold text-white">{ready?.storage ?? "—"}</p>
          </div>
          <div className="card">
            <p className="text-xs uppercase tracking-wide text-slate-500">Retrievals</p>
            <p className="mt-1 text-lg font-bold text-white">
              {metrics?.by_action.memory_retrieved ?? 0}
            </p>
          </div>
          <div className="card">
            <p className="text-xs uppercase tracking-wide text-slate-500">Fallback retrievals</p>
            <p className="mt-1 text-lg font-bold text-white">
              {metrics?.by_action.retrieval_fallback ?? 0}
            </p>
          </div>
          <div className="card">
            <p className="text-xs uppercase tracking-wide text-slate-500">Wrong-tenant blocked</p>
            <p className="mt-1 text-lg font-bold text-white">RLS</p>
            <p className="text-[11px] text-slate-500">enforced at DB</p>
          </div>
          <div className="card">
            <p className="text-xs uppercase tracking-wide text-slate-500">Deleted-memory blocked</p>
            <p className="mt-1 text-lg font-bold text-white">
              {metrics?.by_status.deleted ?? 0}
            </p>
            <p className="text-[11px] text-slate-500">never retrievable</p>
          </div>
        </div>
        <p className="text-xs text-slate-500">
          Tenant isolation is enforced at the database via Postgres Row-Level Security
          (migration <span className="text-slate-300">004_rls_policies.sql</span>,{" "}
          <span className="text-slate-300">FORCE</span> + <span className="text-slate-300">app.tenant_id</span>{" "}
          session GUC), in addition to application-level <span className="text-slate-300">tenant_id</span>/
          <span className="text-slate-300">user_id</span> filtering. See ADR-006.
        </p>
      </div>

      <div className="card space-y-3">
        <h2 className="font-semibold text-white">Loop engineering</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <div className="card">
            <p className="text-xs uppercase tracking-wide text-slate-500">Loop runs</p>
            <p className="mt-1 text-2xl font-bold text-white">
              {metrics?.loops?.total_runs ?? 0}
            </p>
          </div>
          <div className="card">
            <p className="text-xs uppercase tracking-wide text-slate-500">Failed loops</p>
            <p className="mt-1 text-2xl font-bold text-white">
              {metrics?.loops?.failed ?? 0}
            </p>
          </div>
          <div className="card">
            <p className="text-xs uppercase tracking-wide text-slate-500">Safe-degraded</p>
            <p className="mt-1 text-2xl font-bold text-white">
              {metrics?.loops?.safe_degraded ?? 0}
            </p>
          </div>
          <div className="card">
            <p className="text-xs uppercase tracking-wide text-slate-500">Common failure</p>
            <p className="mt-1 text-sm font-semibold text-white">
              {metrics?.loops?.most_common_failure_mode ?? "none"}
            </p>
          </div>
          <div className="card">
            <p className="text-xs uppercase tracking-wide text-slate-500">Release gate</p>
            <p className="mt-1 text-sm font-semibold text-emerald-400">documented</p>
          </div>
        </div>
      </div>

      <div className="card">
        <h2 className="mb-3 font-semibold text-white">Audit log (append-only)</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="p-2">When</th>
                <th className="p-2">Action</th>
                <th className="p-2">Reason</th>
                <th className="p-2">Trace</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((e) => (
                <tr key={e.id} className="border-t border-slate-800">
                  <td className="whitespace-nowrap p-2 text-slate-500">
                    {new Date(e.created_at).toLocaleTimeString()}
                  </td>
                  <td className="p-2">
                    <span className="chip">{e.action}</span>
                  </td>
                  <td className="p-2 text-slate-400">{e.reason}</td>
                  <td className="p-2 text-slate-600">{e.trace_id?.slice(0, 8)}</td>
                </tr>
              ))}
              {audit.length === 0 && (
                <tr>
                  <td className="p-2 text-slate-500" colSpan={4}>
                    No audit events yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
