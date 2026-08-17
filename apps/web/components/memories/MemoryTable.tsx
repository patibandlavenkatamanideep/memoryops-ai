"use client";

import Link from "next/link";

import { MemoryRecord } from "@/lib/api";
import type { UiCapabilities } from "@/lib/capabilities";
import {
  Badge,
  DataTable,
  StatusBadge,
  TBody,
  TD,
  TH,
  THead,
  TR,
  TableEmptyRow,
} from "@/components/ui";
import MemoryActions from "./MemoryActions";

/**
 * The memory registry table.
 *
 * Content is the scanning column and gets the width; every other column is a fixed,
 * narrow, comparable value. The row does not become a link — the actions cell holds
 * real buttons, and nesting interactive controls inside a link is both invalid and
 * unusable with a keyboard.
 */
export default function MemoryTable({
  rows,
  loading,
  onChanged,
  capabilities,
}: {
  rows: MemoryRecord[];
  loading?: boolean;
  onChanged: () => void | Promise<void>;
  capabilities?: UiCapabilities;
}) {
  return (
    <DataTable caption="Governed memories">
      <THead>
        <TH className="w-[38%]">Content</TH>
        <TH>Type</TH>
        <TH>Sensitivity</TH>
        <TH className="text-right">Imp.</TH>
        <TH className="text-right">Conf.</TH>
        <TH>Status</TH>
        <TH>Source</TH>
        <TH>Actions</TH>
      </THead>
      <TBody>
        {rows.map((m) => (
          <TR key={m.id}>
            <TD className="text-fg">
              <Link
                href={`/memories/${m.id}`}
                className="line-clamp-3 rounded-sm hover:text-accent-strong hover:underline"
              >
                {m.content}
              </Link>
            </TD>
            <TD>
              <Badge tone="quiet">{m.memory_type}</Badge>
            </TD>
            <TD className="whitespace-nowrap">{m.sensitivity}</TD>
            <TD className="text-right font-mono text-xs">{m.importance}</TD>
            <TD className="text-right font-mono text-xs">{m.confidence.toFixed(2)}</TD>
            <TD>
              <StatusBadge status={m.status} />
            </TD>
            <TD className="whitespace-nowrap text-xs" title={m.source.excerpt}>
              {m.source.kind}
            </TD>
            <TD>
              <MemoryActions
                memory={m}
                onChanged={onChanged}
                capabilities={capabilities}
              />
            </TD>
          </TR>
        ))}
        {!loading && rows.length === 0 ? (
          <TableEmptyRow colSpan={8}>No memories match these filters.</TableEmptyRow>
        ) : null}
      </TBody>
    </DataTable>
  );
}
