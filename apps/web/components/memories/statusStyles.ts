// Shared status → badge style map for the memory control plane.
// `deleted` is styled distinctly and must never be presented as active.

export const STATUS_STYLES: Record<string, string> = {
  active: "border-emerald-700 text-emerald-300",
  pending: "border-amber-700 text-amber-300",
  archived: "border-slate-600 text-slate-400",
  rejected: "border-rose-800 text-rose-300",
  blocked: "border-rose-800 text-rose-300",
  deleted: "border-slate-700 text-slate-600 line-through",
};

export function statusClass(status: string): string {
  return STATUS_STYLES[status] ?? "border-slate-700 text-slate-300";
}
