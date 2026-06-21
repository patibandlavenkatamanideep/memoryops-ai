"use client";

import { useEffect, useState } from "react";
import { api, LoopDefinition, LoopEvent, LoopRun } from "@/lib/api";
import LoopCard from "@/components/loops/LoopCard";
import LoopEvidencePanel from "@/components/loops/LoopEvidencePanel";
import LoopRunTable from "@/components/loops/LoopRunTable";
import LoopStateMachine from "@/components/loops/LoopStateMachine";
import LoopTimeline from "@/components/loops/LoopTimeline";

export default function LoopsPage() {
  const [loops, setLoops] = useState<LoopDefinition[]>([]);
  const [runs, setRuns] = useState<LoopRun[]>([]);
  const [events, setEvents] = useState<LoopEvent[]>([]);
  const [selected, setSelected] = useState<LoopDefinition | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const [defs, recentRuns, recentEvents] = await Promise.all([
          api.loops(),
          api.loopRuns(),
          api.loopEvents(),
        ]);
        setLoops(defs);
        setSelected(defs[0] ?? null);
        setRuns(recentRuns);
        setEvents(recentEvents);
      } catch (e) {
        setError(String(e));
      }
    }
    load();
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Loop Engineering</h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-400">
          MemoryOps models memory as governed loops: observe, decide, act, verify, audit,
          and learn.
        </p>
      </div>
      {error && <p className="text-sm text-rose-400">API error: {error}</p>}
      <LoopEvidencePanel loops={loops} />
      <div className="grid gap-3 lg:grid-cols-2">
        {loops.map((loop) => (
          <button key={loop.id} className="text-left" onClick={() => setSelected(loop)}>
            <LoopCard loop={loop} />
          </button>
        ))}
      </div>
      {selected && <LoopStateMachine loop={selected} />}
      <div className="grid gap-4 lg:grid-cols-2">
        <LoopRunTable runs={runs} />
        <LoopTimeline events={events} />
      </div>
    </div>
  );
}
