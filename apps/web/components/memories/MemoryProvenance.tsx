"use client";

import { MemoryProvenance as Provenance } from "@/lib/api";
import {
  Badge,
  DefinitionList,
  FieldLabel,
  KeyValue,
  MonoId,
  Panel,
  PanelBody,
  PanelHeader,
  SourceQuote,
} from "@/components/ui";

// Renders where a memory came from (source/provenance, invariant #3) and the
// durable signals that explain why it persists and gets retrieved.
export default function MemoryProvenance({ provenance }: { provenance: Provenance | null }) {
  if (!provenance) return null;
  const s = provenance.source;

  return (
    <Panel>
      <PanelHeader
        title="Provenance & explainability"
        description="Where this memory came from, and the durable signals behind its retrieval."
      />
      <PanelBody className="space-y-5">
        <DefinitionList columns={3}>
          <KeyValue label="Source kind">{s.kind}</KeyValue>
          <KeyValue label="Status">{provenance.status}</KeyValue>
          <KeyValue label="Reinforcement count">{provenance.reinforcement_count}</KeyValue>
          <KeyValue label="Created">
            {new Date(provenance.created_at).toLocaleString()}
          </KeyValue>
          <KeyValue label="Updated">
            {new Date(provenance.updated_at).toLocaleString()}
          </KeyValue>
          {s.conversation_id ? (
            <KeyValue label="Conversation" mono>
              {s.conversation_id}
            </KeyValue>
          ) : null}
          {s.message_id ? (
            <KeyValue label="Message" mono>
              {s.message_id}
            </KeyValue>
          ) : null}
        </DefinitionList>

        {s.excerpt ? (
          <div className="space-y-1.5">
            <FieldLabel>Source excerpt</FieldLabel>
            <SourceQuote>{s.excerpt}</SourceQuote>
          </div>
        ) : null}

        <div className="space-y-2">
          <FieldLabel>Ranking signals</FieldLabel>
          <div className="flex flex-wrap gap-2">
            <Badge tone="quiet">importance {provenance.importance}</Badge>
            <Badge tone="quiet">confidence {provenance.confidence.toFixed(2)}</Badge>
            <Badge tone="quiet">weight {provenance.weight.toFixed(2)}</Badge>
            <Badge tone="quiet">reinforced ×{provenance.reinforcement_count}</Badge>
          </div>
          <p className="text-xs leading-relaxed text-fg-muted">
            The ranker scores candidates on vector similarity, keyword overlap and these
            durable signals. Per-request retrieval scores are shown live in the Chat view.
          </p>
        </div>

        {provenance.loop_run_ids.length > 0 ? (
          <div className="space-y-2">
            <FieldLabel>Loop evidence ({provenance.loop_run_ids.length})</FieldLabel>
            <div className="flex flex-wrap gap-2">
              {provenance.loop_run_ids.map((id) => (
                <MonoId key={id} value={id} chars={10} label="run" />
              ))}
            </div>
          </div>
        ) : null}
      </PanelBody>
    </Panel>
  );
}
