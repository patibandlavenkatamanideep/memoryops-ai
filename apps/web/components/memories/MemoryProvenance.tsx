"use client";

import { MemoryProvenance as Provenance } from "@/lib/api";

// Renders where a memory came from (source/provenance, invariant #3) and the
// durable signals that explain why it persists and gets retrieved.
export default function MemoryProvenance({ provenance }: { provenance: Provenance | null }) {
  if (!provenance) return null;
  const s = provenance.source;
  return (
    <section className="card space-y-4">
      <h3 className="font-semibold text-white">Provenance &amp; explainability</h3>

      <div className="grid gap-2 text-sm sm:grid-cols-2">
        <Field label="Source kind" value={s.kind} />
        <Field label="Reinforcement count" value={String(provenance.reinforcement_count)} />
        <Field label="Created" value={new Date(provenance.created_at).toLocaleString()} />
        <Field label="Updated" value={new Date(provenance.updated_at).toLocaleString()} />
        {s.conversation_id && <Field label="Conversation" value={s.conversation_id} />}
        {s.message_id && <Field label="Message" value={s.message_id} />}
      </div>

      {s.excerpt && (
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Source excerpt</p>
          <blockquote className="mt-1 border-l-2 border-slate-700 pl-3 text-sm text-slate-300">
            {s.excerpt}
          </blockquote>
        </div>
      )}

      <div>
        <p className="text-xs uppercase tracking-wide text-slate-500">
          Why this memory is used (ranking signals)
        </p>
        <div className="mt-2 flex flex-wrap gap-2 text-xs">
          <span className="chip">importance {provenance.importance}</span>
          <span className="chip">confidence {provenance.confidence.toFixed(2)}</span>
          <span className="chip">weight {provenance.weight.toFixed(2)}</span>
          <span className="chip">reinforced ×{provenance.reinforcement_count}</span>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          The ranker scores candidates on vector similarity, keyword overlap, and these
          durable signals. Per-request retrieval scores are shown live in the Chat view.
        </p>
      </div>

      {provenance.loop_run_ids.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Loop evidence</p>
          <div className="mt-2 flex flex-wrap gap-1">
            {provenance.loop_run_ids.map((id) => (
              <span key={id} className="chip font-mono text-[10px]">
                {id.slice(0, 8)}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="text-slate-200">{value}</p>
    </div>
  );
}
