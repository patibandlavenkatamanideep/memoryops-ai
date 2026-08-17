import { LoopEvent } from "@/lib/api";
import {
  Badge,
  Disclosure,
  EmptyState,
  EvidenceBlock,
  MonoId,
  Timeline,
  TimelineItem,
  toneForRunStatus,
} from "@/components/ui";

/**
 * Loop state transitions, newest first.
 *
 * The `evidence` object is shown verbatim behind a disclosure rather than summarised.
 * Loop evidence is the artefact an operator is here to read; paraphrasing it would put
 * this component between them and the record.
 */
export default function LoopTimeline({ events }: { events: LoopEvent[] }) {
  if (events.length === 0) {
    return (
      <EmptyState
        title="No loop events yet"
        description="Loop events are emitted as background lifecycle work transitions between states."
      />
    );
  }

  return (
    <Timeline>
      {events.slice(0, 12).map((event) => (
        <TimelineItem
          key={event.id}
          tone={toneForRunStatus(event.state_to)}
          title={<span className="font-mono text-xs">{event.loop_id}</span>}
          timestamp={new Date(event.created_at).toLocaleString()}
          description={event.reason}
          meta={
            <>
              {event.state_from ? (
                <Badge tone="quiet">{event.state_from}</Badge>
              ) : null}
              <span aria-hidden className="text-fg-muted">
                →
              </span>
              <Badge tone={toneForRunStatus(event.state_to)}>{event.state_to}</Badge>
              <Badge tone="quiet">{event.event_type}</Badge>
              <MonoId label="trace" value={event.trace_id} chars={10} />
            </>
          }
        >
          {Object.keys(event.evidence ?? {}).length > 0 ? (
            <Disclosure summary="Evidence" className="mt-2">
              <EvidenceBlock value={event.evidence} label={`Evidence for ${event.loop_id}`} />
            </Disclosure>
          ) : null}
        </TimelineItem>
      ))}
    </Timeline>
  );
}
