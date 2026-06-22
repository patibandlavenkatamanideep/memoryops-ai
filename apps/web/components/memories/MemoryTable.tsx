"use client";

import Link from "next/link";
import { MemoryRecord } from "@/lib/api";
import { statusClass } from "./statusStyles";
import MemoryActions from "./MemoryActions";

export default function MemoryTable({
  rows,
  loading,
  onChanged,
}: {
  rows: MemoryRecord[];
  loading?: boolean;
  onChanged: () => void | Promise<void>;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="p-2">Content</th>
            <th className="p-2">Type</th>
            <th className="p-2">Sens.</th>
            <th className="p-2">Imp.</th>
            <th className="p-2">Conf.</th>
            <th className="p-2">Status</th>
            <th className="p-2">Source</th>
            <th className="p-2">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.id} className="border-t border-slate-800 align-top">
              <td className="max-w-xs p-2">
                <Link href={`/memories/${m.id}`} className="hover:text-white hover:underline">
                  {m.content}
                </Link>
              </td>
              <td className="p-2 text-slate-400">{m.memory_type}</td>
              <td className="p-2 text-slate-400">{m.sensitivity}</td>
              <td className="p-2 text-slate-400">{m.importance}</td>
              <td className="p-2 text-slate-400">{m.confidence.toFixed(2)}</td>
              <td className="p-2">
                <span className={`chip ${statusClass(m.status)}`}>{m.status}</span>
              </td>
              <td
                className="max-w-[10rem] truncate p-2 text-slate-500"
                title={m.source.excerpt}
              >
                {m.source.kind}
              </td>
              <td className="p-2">
                <MemoryActions memory={m} onChanged={onChanged} />
              </td>
            </tr>
          ))}
          {!loading && rows.length === 0 && (
            <tr>
              <td className="p-2 text-slate-500" colSpan={8}>
                No memories match these filters.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
