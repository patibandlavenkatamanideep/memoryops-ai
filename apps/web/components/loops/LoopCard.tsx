import { LoopDefinition } from "@/lib/api";

export default function LoopCard({ loop }: { loop: LoopDefinition }) {
  return (
    <article className="card space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-white">{loop.name}</h2>
          <p className="mt-1 text-sm text-slate-400">{loop.purpose}</p>
        </div>
        <span className="chip border-accent text-accent">{loop.id}</span>
      </div>
      <p className="text-xs text-slate-500">Trigger: {loop.trigger}</p>
      <div>
        <p className="text-xs uppercase tracking-wide text-slate-500">Evidence required</p>
        <div className="mt-2 flex flex-wrap gap-1">
          {loop.evidence_required.map((item) => (
            <span key={item} className="chip">
              {item}
            </span>
          ))}
        </div>
      </div>
    </article>
  );
}
