"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, api, AuditEvent } from "@/lib/api";
import AuditTimeline from "@/components/audit/AuditTimeline";
import {
  Badge,
  Button,
  ErrorState,
  LoadingState,
  MetricCard,
  MetricGrid,
  PageHeader,
  Panel,
  PanelBody,
  PanelFooter,
  PanelHeader,
  SectionHeader,
} from "@/components/ui";

type Metrics = Awaited<ReturnType<typeof api.metrics>>;
type Ready = Awaited<ReturnType<typeof api.ready>>;
type EvalSummary = {
  passed: number;
  total: number;
  pass_rate: number;
  loop_engineering?: Record<string, string | boolean | number | null>;
};

/**
 * Operational view of the runtime.
 *
 * Everything on this page is a value the API returned. Two things that used to sit in
 * metric cards no longer do: "Wrong-tenant blocked: RLS" and "Release gate: documented"
 * were statements about the codebase rendered in the shape of measurements, so they
 * read as counters that were always healthy. They are now prose in the panel footer,
 * where a claim belongs.
 *
 * A metric that has not loaded renders as pending rather than as `0` — on an
 * operations surface, "none happened" and "we could not ask" must not look identical.
 */
export default function AdminPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [ready, setReady] = useState<Ready | null>(null);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [evals, setEvals] = useState<EvalSummary | null>(null);
  const [evalsRunning, setEvalsRunning] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [m, a, r] = await Promise.all([api.metrics(), api.audit(), api.ready()]);
      setMetrics(m);
      setAudit(a);
      setReady(r);
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

  async function runEvals() {
    setEvalsRunning(true);
    try {
      setEvals(await api.runEvals());
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? `Eval run failed: ${e.status}.` : String(e));
    } finally {
      setEvalsRunning(false);
    }
  }

  /** `null` while metrics are unknown, so the card shows pending rather than zero. */
  const count = (value: number | undefined) => (metrics ? (value ?? 0) : null);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Operations"
        title="Admin"
        description="Runtime counters, retrieval configuration and readiness for this tenant, as reported by the API."
        actions={
          <>
            <Button size="sm" onClick={() => void load()} disabled={loading}>
              {loading ? "Refreshing…" : "Refresh"}
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => void runEvals()}
              disabled={evalsRunning}
            >
              {evalsRunning ? "Running evals…" : "Run evals"}
            </Button>
          </>
        }
      />

      {error ? (
        <ErrorState
          detail={error}
          action={
            <Button size="sm" onClick={() => void load()}>
              Retry
            </Button>
          }
        />
      ) : null}

      {loading && !metrics ? <LoadingState label="Loading runtime state…" rows={4} /> : null}

      {evals ? (
        <Panel tone={evals.passed === evals.total ? "ok" : "warn"}>
          <PanelHeader
            title="Eval run"
            description="Result of the run you just triggered, not a stored or historical score."
            actions={
              <Badge tone={evals.passed === evals.total ? "ok" : "warn"}>
                {evals.passed}/{evals.total} passed · {(evals.pass_rate * 100).toFixed(0)}%
              </Badge>
            }
          />
          {evals.loop_engineering && Object.keys(evals.loop_engineering).length > 0 ? (
            <PanelBody>
              <div className="flex flex-wrap gap-2">
                {Object.entries(evals.loop_engineering).map(([loop, status]) => (
                  <Badge key={loop} tone="quiet">
                    {loop.replace(/_/g, " ")}: {String(status)}
                  </Badge>
                ))}
              </div>
            </PanelBody>
          ) : null}
        </Panel>
      ) : null}

      <section className="space-y-3">
        <SectionHeader
          title="Memory inventory"
          description="Counts across the governed lifecycle for this tenant."
        />
        <MetricGrid>
          <MetricCard label="Total memories" value={count(metrics?.total_memories)} />
          <MetricCard label="Active" value={count(metrics?.by_status.active)} tone="ok" />
          <MetricCard label="Pending approval" value={count(metrics?.by_status.pending)} tone="warn" />
          <MetricCard label="Blocked" value={count(metrics?.by_action.memory_blocked)} tone="danger" />
          <MetricCard
            label="Deleted"
            value={count(metrics?.by_status.deleted)}
            hint="Excluded from every retrieval path"
          />
          <MetricCard label="Retrievals" value={count(metrics?.by_action.memory_retrieved)} />
          <MetricCard
            label="Fallback retrievals"
            value={count(metrics?.by_action.retrieval_fallback)}
            hint="Keyword-only, after an embedding failure"
          />
          <MetricCard label="Audit events" value={count(metrics?.audit_events)} />
        </MetricGrid>
      </section>

      <section className="space-y-3">
        <SectionHeader
          title="Retrieval & data layer"
          description="Configuration reported by the API's readiness endpoint."
        />
        <Panel>
          <PanelBody>
            <MetricGrid className="lg:grid-cols-3">
              <MetricCard
                label="Embedding provider"
                value={
                  ready ? (
                    <span className="text-lg">
                      {ready.embeddings_provider}
                      <span className="ml-1.5 text-sm font-normal text-fg-muted">
                        {ready.embedding_dim}d
                      </span>
                    </span>
                  ) : null
                }
              />
              <MetricCard
                label="Storage"
                value={ready ? <span className="text-lg">{ready.storage}</span> : null}
              />
              <MetricCard
                label="LLM provider"
                value={ready ? <span className="text-lg">{ready.llm_provider}</span> : null}
              />
            </MetricGrid>

            {ready?.checks && Object.keys(ready.checks).length > 0 ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {Object.entries(ready.checks).map(([name, check]) => (
                  <Badge
                    key={name}
                    tone={check.status === "ok" ? "ok" : "warn"}
                    title={check.reason_code}
                  >
                    {name}: {check.status}
                  </Badge>
                ))}
              </div>
            ) : null}
          </PanelBody>
          <PanelFooter>
            Tenant isolation is enforced at the database by Postgres Row-Level Security
            (migration <span className="font-mono">004_rls_policies.sql</span>,{" "}
            <span className="font-mono">FORCE</span> plus the{" "}
            <span className="font-mono">app.tenant_id</span> session GUC) in addition to
            application-level <span className="font-mono">tenant_id</span>/
            <span className="font-mono">user_id</span> filtering. See ADR-006. This is a
            property of the deployment, not a counter — the API returns no
            wrong-tenant-attempt metric.
          </PanelFooter>
        </Panel>
      </section>

      <section className="space-y-3">
        <SectionHeader
          title="Loop engineering"
          description="Aggregate loop-run counters from the metrics endpoint."
        />
        <MetricGrid className="lg:grid-cols-4">
          <MetricCard label="Loop runs" value={count(metrics?.loops?.total_runs)} />
          <MetricCard label="Failed" value={count(metrics?.loops?.failed)} tone="danger" />
          <MetricCard
            label="Safe-degraded"
            value={count(metrics?.loops?.safe_degraded)}
            tone="warn"
            hint="Degraded without blocking a response"
          />
          <MetricCard
            label="Most common failure"
            value={
              metrics ? (
                <span className="text-base">
                  {metrics.loops?.most_common_failure_mode ?? "none recorded"}
                </span>
              ) : null
            }
          />
        </MetricGrid>
      </section>

      <section className="space-y-3">
        <SectionHeader
          title="Audit log"
          description="Append-only lifecycle history across this tenant, newest first."
        />
        <Panel>
          <PanelBody>
            <AuditTimeline events={audit} />
          </PanelBody>
        </Panel>
      </section>
    </div>
  );
}
