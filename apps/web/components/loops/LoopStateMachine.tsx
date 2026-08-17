import { LoopDefinition } from "@/lib/api";
import { Badge, FieldLabel, Panel, PanelBody, PanelHeader } from "@/components/ui";

export default function LoopStateMachine({ loop }: { loop: LoopDefinition }) {
  return (
    <Panel>
      <PanelHeader
        title={`State machine — ${loop.name}`}
        description={`${loop.input_contract} → ${loop.output_contract}`}
      />
      <PanelBody className="space-y-5">
        <ol className="flex flex-wrap items-center gap-1.5">
          {loop.states.map((state, index) => (
            <li key={`${loop.id}-${state}`} className="flex items-center gap-1.5">
              {index > 0 ? (
                <span aria-hidden className="text-fg-muted">
                  →
                </span>
              ) : null}
              <Badge tone="neutral">{state}</Badge>
            </li>
          ))}
        </ol>

        <div className="grid gap-5 md:grid-cols-3">
          <StateList title="Policy gates" items={loop.policy_gates} />
          <StateList title="Failure modes" items={loop.failure_modes} />
          <StateList title="Fallback behaviour" items={loop.fallback_behavior} />
        </div>
      </PanelBody>
    </Panel>
  );
}

function StateList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="space-y-2">
      <FieldLabel>{title}</FieldLabel>
      {items.length === 0 ? (
        <p className="text-xs text-fg-muted">None declared.</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item) => (
            <li key={item} className="flex gap-2 text-xs leading-relaxed text-fg-secondary">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-line-strong" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
