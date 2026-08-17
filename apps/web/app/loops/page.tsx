"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, api, LoopDefinition, LoopEvent, LoopRun } from "@/lib/api";
import LoopCard from "@/components/loops/LoopCard";
import LoopEvidencePanel from "@/components/loops/LoopEvidencePanel";
import LoopRunTable from "@/components/loops/LoopRunTable";
import LoopStateMachine from "@/components/loops/LoopStateMachine";
import LoopTimeline from "@/components/loops/LoopTimeline";
import {
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Panel,
  PanelBody,
  PanelHeader,
  SectionHeader,
} from "@/components/ui";

export default function LoopsPage() {
  const [loops, setLoops] = useState<LoopDefinition[]>([]);
  const [runs, setRuns] = useState<LoopRun[]>([]);
  const [events, setEvents] = useState<LoopEvent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [defs, recentRuns, recentEvents] = await Promise.all([
        api.loops(),
        api.loopRuns(),
        api.loopEvents(),
      ]);
      setLoops(defs);
      // Track the selection by id, not by object identity: a refresh replaces every
      // definition, and holding the old object silently detached the state machine
      // from the list the operator was looking at.
      setSelectedId((current) =>
        current && defs.some((d) => d.id === current) ? current : (defs[0]?.id ?? null),
      );
      setRuns(recentRuns);
      setEvents(recentEvents);
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

  const selected = loops.find((loop) => loop.id === selectedId) ?? null;

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Operations"
        title="Loops"
        description="MemoryOps models memory work as typed loops — observe, decide, act, verify, audit, learn. Each definition declares its policy gates, failure modes and the evidence a run must produce."
        actions={
          <Button size="sm" onClick={() => void load()} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </Button>
        }
      />

      {error ? (
        <ErrorState
          title="Could not load loop state"
          detail={error}
          action={
            <Button size="sm" onClick={() => void load()}>
              Retry
            </Button>
          }
        />
      ) : null}

      {loading && loops.length === 0 ? (
        <LoadingState label="Loading loop definitions…" rows={4} />
      ) : null}

      <LoopEvidencePanel loops={loops} />

      <section className="space-y-3">
        <SectionHeader
          title="Loop definitions"
          count={loops.length > 0 ? `${loops.length} defined` : undefined}
          description="Select a loop to inspect its state machine."
        />
        {loops.length === 0 && !loading ? (
          <EmptyState
            title="No loop definitions returned"
            description="The API did not return any loop definitions for this tenant."
          />
        ) : (
          <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
            {loops.map((loop) => (
              <LoopCard
                key={loop.id}
                loop={loop}
                selected={loop.id === selectedId}
                onSelect={() => setSelectedId(loop.id)}
              />
            ))}
          </div>
        )}
      </section>

      {selected ? <LoopStateMachine loop={selected} /> : null}

      <section className="grid gap-4 2xl:grid-cols-2">
        <div className="min-w-0 space-y-3">
          <SectionHeader
            title="Recent runs"
            description="Loop executions recorded for this tenant."
          />
          <LoopRunTable runs={runs} />
        </div>
        <div className="min-w-0 space-y-3">
          <SectionHeader
            title="Recent events"
            description="State transitions with the evidence each carried."
          />
          <Panel>
            <PanelHeader title="Loop event timeline" />
            <PanelBody>
              <LoopTimeline events={events} />
            </PanelBody>
          </Panel>
        </div>
      </section>
    </div>
  );
}
