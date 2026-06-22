"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, MemoryRecord } from "@/lib/api";
import MemoryTable from "@/components/memories/MemoryTable";
import MemoryFilters, {
  EMPTY_FILTERS,
  MemoryFilterState,
} from "@/components/memories/MemoryFilters";

export default function MemoriesPage() {
  const [rows, setRows] = useState<MemoryRecord[]>([]);
  const [filters, setFilters] = useState<MemoryFilterState>(EMPTY_FILTERS);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  // status/type filter server-side (tenant-scoped); search is client-side.
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(
        await api.memories({
          status: filters.status || undefined,
          memory_type: filters.memory_type || undefined,
        })
      );
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [filters.status, filters.memory_type]);

  useEffect(() => {
    load();
  }, [load]);

  const visible = useMemo(() => {
    const q = filters.search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((m) => m.content.toLowerCase().includes(q));
  }, [rows, filters.search]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Memories</h1>
        <p className="mt-1 text-sm text-slate-400">
          Governed memory inventory. Soft-deleted memories are never listed here.
        </p>
      </div>
      {error && <p className="text-sm text-rose-400">API error: {error}</p>}
      <MemoryFilters value={filters} onChange={setFilters} />
      {loading && <p className="text-sm text-slate-400">Loading…</p>}
      <MemoryTable rows={visible} loading={loading} onChanged={load} />
    </div>
  );
}
