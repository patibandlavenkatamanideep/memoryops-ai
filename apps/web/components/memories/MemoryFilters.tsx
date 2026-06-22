"use client";

export interface MemoryFilterState {
  search: string;
  status: string;
  memory_type: string;
}

export const EMPTY_FILTERS: MemoryFilterState = {
  search: "",
  status: "",
  memory_type: "",
};

// `deleted` is intentionally absent: the control plane never lists deleted
// rows as part of the active inventory (deletion guarantee, invariant #2).
const STATUSES = ["active", "pending", "archived", "rejected", "blocked"];
const TYPES = [
  "episodic",
  "semantic",
  "procedural",
  "project",
  "knowledge",
  "system",
  "constraint",
  "preference",
  "workflow",
];

export default function MemoryFilters({
  value,
  onChange,
}: {
  value: MemoryFilterState;
  onChange: (next: MemoryFilterState) => void;
}) {
  const select = "rounded-lg border border-slate-700 bg-panel px-3 py-2 text-sm";
  return (
    <div className="flex flex-wrap items-center gap-3">
      <input
        className="grow rounded-lg border border-slate-700 bg-panel px-3 py-2 text-sm"
        placeholder="Search content…"
        value={value.search}
        onChange={(e) => onChange({ ...value, search: e.target.value })}
      />
      <select
        className={select}
        value={value.status}
        onChange={(e) => onChange({ ...value, status: e.target.value })}
      >
        <option value="">All statuses</option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <select
        className={select}
        value={value.memory_type}
        onChange={(e) => onChange({ ...value, memory_type: e.target.value })}
      >
        <option value="">All types</option>
        {TYPES.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      {(value.search || value.status || value.memory_type) && (
        <button
          className="text-sm text-slate-400 hover:text-white"
          onClick={() => onChange(EMPTY_FILTERS)}
        >
          clear
        </button>
      )}
    </div>
  );
}
