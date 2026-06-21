import { LoopDefinition } from "@/lib/api";

export default function LoopStateMachine({ loop }: { loop: LoopDefinition }) {
  return (
    <div className="card space-y-3">
      <h2 className="font-semibold text-white">State machine</h2>
      <div className="flex flex-wrap gap-2">
        {loop.states.map((state, index) => (
          <span key={`${loop.id}-${state}`} className="chip border-slate-600">
            {index + 1}. {state}
          </span>
        ))}
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <Panel title="Policy gates" items={loop.policy_gates} />
        <Panel title="Failure modes" items={loop.failure_modes} />
        <Panel title="Fallback behavior" items={loop.fallback_behavior} />
      </div>
    </div>
  );
}

function Panel({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-slate-500">{title}</p>
      <ul className="mt-2 space-y-1 text-sm text-slate-400">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
