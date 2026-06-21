import { LoopEvent } from "@/lib/api";

export default function LoopTimeline({ events }: { events: LoopEvent[] }) {
  return (
    <div className="card">
      <h2 className="mb-3 font-semibold text-white">Recent loop events</h2>
      <div className="space-y-2">
        {events.slice(0, 12).map((event) => (
          <div key={event.id} className="rounded-lg border border-slate-800 p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="chip border-accent text-accent">{event.loop_id}</span>
              <span className="chip">{event.state_to}</span>
              <span className="text-slate-500">{event.event_type}</span>
            </div>
            <p className="mt-2 text-slate-300">{event.reason}</p>
            <p className="mt-1 text-xs text-slate-600">trace {event.trace_id.slice(0, 8)}</p>
          </div>
        ))}
        {events.length === 0 && <p className="text-sm text-slate-500">No loop events yet.</p>}
      </div>
    </div>
  );
}
