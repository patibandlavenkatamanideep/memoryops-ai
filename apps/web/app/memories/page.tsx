"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, api, MemoryRecord } from "@/lib/api";
import MemoryTable from "@/components/memories/MemoryTable";
import MemoryFilters, {
  EMPTY_FILTERS,
  MemoryFilterState,
} from "@/components/memories/MemoryFilters";
import {
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from "@/components/ui";

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
      setError(
        e instanceof ApiError ? `The API returned ${e.status}.` : String(e),
      );
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

  const filtered = Boolean(filters.search || filters.status || filters.memory_type);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Runtime"
        title="Memories"
        description="Governed memory inventory for this tenant. Each row is typed, provenanced and carries a lifecycle status. Soft-deleted memories are never listed here."
        actions={
          <Button size="sm" onClick={() => void load()} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </Button>
        }
      />

      <MemoryFilters value={filters} onChange={setFilters} />

      {error ? (
        <ErrorState
          title="Could not load memories"
          detail={error}
          action={
            <Button size="sm" onClick={() => void load()}>
              Retry
            </Button>
          }
        />
      ) : null}

      {loading && rows.length === 0 ? (
        <LoadingState label="Loading memories…" rows={5} />
      ) : !error && rows.length === 0 ? (
        <EmptyState
          title={filtered ? "No memories match these filters" : "No governed memories yet"}
          description={
            filtered
              ? "Clear the filters to see the full inventory for this tenant."
              : "Memories appear once a chat turn produces a candidate that the policy broker admits. Nothing is stored without an audited decision."
          }
          action={
            filtered ? (
              <Button size="sm" onClick={() => setFilters(EMPTY_FILTERS)}>
                Clear filters
              </Button>
            ) : null
          }
        />
      ) : (
        <>
          <p className="text-xs text-fg-muted">
            Showing {visible.length} of {rows.length} loaded {rows.length === 1 ? "memory" : "memories"}.
          </p>
          <MemoryTable rows={visible} loading={loading} onChanged={load} />
        </>
      )}
    </div>
  );
}
