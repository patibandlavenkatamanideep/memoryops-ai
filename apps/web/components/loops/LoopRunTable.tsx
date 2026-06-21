import { LoopRun } from "@/lib/api";

export default function LoopRunTable({ runs }: { runs: LoopRun[] }) {
  return (
    <div className="card">
      <h2 className="mb-3 font-semibold text-white">Recent loop runs</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="p-2">Loop</th>
              <th className="p-2">Status</th>
              <th className="p-2">Trace</th>
              <th className="p-2">Started</th>
            </tr>
          </thead>
          <tbody>
            {runs.slice(0, 12).map((run) => (
              <tr key={run.id} className="border-t border-slate-800">
                <td className="p-2">{run.loop_id}</td>
                <td className="p-2">
                  <span className="chip">{run.status}</span>
                </td>
                <td className="p-2 text-slate-500">{run.trace_id.slice(0, 8)}</td>
                <td className="p-2 text-slate-500">
                  {new Date(run.started_at).toLocaleTimeString()}
                </td>
              </tr>
            ))}
            {runs.length === 0 && (
              <tr>
                <td className="p-2 text-slate-500" colSpan={4}>
                  No loop runs yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
