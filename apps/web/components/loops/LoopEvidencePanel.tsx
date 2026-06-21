import { LoopDefinition } from "@/lib/api";

export default function LoopEvidencePanel({ loops }: { loops: LoopDefinition[] }) {
  const totalGates = loops.reduce((sum, loop) => sum + loop.policy_gates.length, 0);
  const totalFailureModes = loops.reduce((sum, loop) => sum + loop.failure_modes.length, 0);
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <div className="card">
        <p className="text-xs uppercase tracking-wide text-slate-500">Defined loops</p>
        <p className="mt-1 text-2xl font-bold text-white">{loops.length}</p>
      </div>
      <div className="card">
        <p className="text-xs uppercase tracking-wide text-slate-500">Policy gates</p>
        <p className="mt-1 text-2xl font-bold text-white">{totalGates}</p>
      </div>
      <div className="card">
        <p className="text-xs uppercase tracking-wide text-slate-500">Failure modes modeled</p>
        <p className="mt-1 text-2xl font-bold text-white">{totalFailureModes}</p>
      </div>
    </div>
  );
}
