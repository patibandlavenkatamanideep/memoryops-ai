"use client";

import { Button, Field, Select, TextInput, Toolbar } from "@/components/ui";

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

/**
 * Registry filters.
 *
 * Every control is labelled rather than relying on its placeholder: the search box
 * previously had no accessible name at all, so it was announced as an unlabelled text
 * field. Status and type filter server-side; search is client-side over what was
 * returned, and the hint says so instead of leaving that difference to be discovered.
 */
export default function MemoryFilters({
  value,
  onChange,
}: {
  value: MemoryFilterState;
  onChange: (next: MemoryFilterState) => void;
}) {
  const dirty = Boolean(value.search || value.status || value.memory_type);

  return (
    <Toolbar search>
      <Field
        label="Search content"
        className="min-w-[14rem] flex-1"
        hint="Filters the loaded rows in the browser."
      >
        <TextInput
          type="search"
          placeholder="Search content…"
          value={value.search}
          onChange={(e) => onChange({ ...value, search: e.target.value })}
        />
      </Field>

      <Field label="Status" className="w-40">
        <Select
          value={value.status}
          onChange={(e) => onChange({ ...value, status: e.target.value })}
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>
      </Field>

      <Field label="Type" className="w-44">
        <Select
          value={value.memory_type}
          onChange={(e) => onChange({ ...value, memory_type: e.target.value })}
        >
          <option value="">All types</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </Select>
      </Field>

      {dirty ? (
        <Button variant="ghost" size="sm" onClick={() => onChange(EMPTY_FILTERS)}>
          Clear filters
        </Button>
      ) : null}
    </Toolbar>
  );
}
