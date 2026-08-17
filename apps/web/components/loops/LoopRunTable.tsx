import { LoopRun } from "@/lib/api";
import {
  DataTable,
  MonoId,
  Badge,
  TBody,
  TD,
  TH,
  THead,
  TR,
  TableEmptyRow,
  toneForRunStatus,
} from "@/components/ui";

export default function LoopRunTable({ runs }: { runs: LoopRun[] }) {
  return (
    <DataTable caption="Recent loop runs" className="min-w-0">
      <THead>
        <TH>Loop</TH>
        <TH>Status</TH>
        <TH>Trace</TH>
        <TH>Started</TH>
      </THead>
      <TBody>
        {runs.slice(0, 12).map((run) => (
          <TR key={run.id}>
            <TD className="whitespace-nowrap font-mono text-xs text-fg">{run.loop_id}</TD>
            <TD>
              <Badge tone={toneForRunStatus(run.status)}>{run.status}</Badge>
            </TD>
            <TD>
              <MonoId value={run.trace_id} chars={10} />
            </TD>
            <TD className="whitespace-nowrap text-xs">
              {new Date(run.started_at).toLocaleString()}
            </TD>
          </TR>
        ))}
        {runs.length === 0 ? (
          <TableEmptyRow colSpan={4}>
            No loop runs recorded for this tenant yet.
          </TableEmptyRow>
        ) : null}
      </TBody>
    </DataTable>
  );
}
