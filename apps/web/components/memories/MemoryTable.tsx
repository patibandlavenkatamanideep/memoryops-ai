"use client";

import Link from "next/link";

import { MemoryRecord } from "@/lib/api";
import type { UiCapabilities } from "@/lib/capabilities";
import {
  Badge,
  DataTable,
  EmptyState,
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
 * The memory registry, in two presentations of the same records.
 *
 * Below `md` the eight-column table is replaced by a card list rather than left to
 * scroll sideways. The table needs ~40rem, so on a 390px viewport Status
 * and Actions sat roughly 600px off-screen inside the scroll region: an operator
 * could not see a memory's lifecycle state, let alone act on it, without discovering
 * that the region scrolled horizontally at all.
 *
 * The card carries every field the row does — content, type, sensitivity, importance,
 * confidence, status, source and the same actions — so this is a reflow, not a
 * mobile-only subset. Only one presentation is in the accessibility tree at a time;
 * the hidden one is removed with `hidden`, not merely visually clipped, so a screen
 * reader never encounters both.
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
  const empty = !loading && rows.length === 0;

  return (
    <>
      {/* ── narrow: card list ─────────────────────────────────────────────── */}
      <div className="md:hidden">
        {empty ? (
          <EmptyState title="No memories match these filters." />
        ) : (
          <ul className="space-y-3">
            {rows.map((m) => (
              <li
                key={m.id}
                className="space-y-3 rounded-panel border border-line bg-surface p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={m.status} />
                  <Badge tone="quiet">{m.memory_type}</Badge>
                </div>

                <Link
                  href={`/memories/${m.id}`}
                  className="block break-words rounded-sm text-sm leading-relaxed text-fg underline-offset-4 hover:text-accent-strong hover:underline"
                >
                  {m.content}
                </Link>

                <dl className="grid grid-cols-2 gap-x-4 gap-y-2 border-t border-line pt-3 text-xs">
                  <div>
                    <dt className="text-fg-muted">Sensitivity</dt>
                    <dd className="text-fg-secondary">{m.sensitivity}</dd>
                  </div>
                  <div>
                    <dt className="text-fg-muted">Source</dt>
                    <dd className="break-words text-fg-secondary">{m.source.kind}</dd>
                  </div>
                  <div>
                    <dt className="text-fg-muted">Importance</dt>
                    <dd className="font-mono text-fg-secondary">{m.importance}</dd>
                  </div>
                  <div>
                    <dt className="text-fg-muted">Confidence</dt>
                    <dd className="font-mono text-fg-secondary">
                      {m.confidence.toFixed(2)}
                    </dd>
                  </div>
                </dl>

                <div className="border-t border-line pt-3">
                  <MemoryActions
                    memory={m}
                    onChanged={onChanged}
                    capabilities={capabilities}
                  />
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* ── md and wider: dense table ─────────────────────────────────────── */}
      <div className="hidden md:block">
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
                    className="line-clamp-3 break-words rounded-sm hover:text-accent-strong hover:underline"
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
            {empty ? (
              <TableEmptyRow colSpan={8}>No memories match these filters.</TableEmptyRow>
            ) : null}
          </TBody>
        </DataTable>
      </div>
    </>
  );
}
