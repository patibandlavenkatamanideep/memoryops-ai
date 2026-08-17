import { LoopDefinition } from "@/lib/api";
import { MetricCard, MetricGrid } from "@/components/ui";

/**
 * Counts derived from the loop definitions the API returned.
 *
 * `null` until definitions arrive, so an empty response reads as "not loaded" rather
 * than as a runtime that models zero loops.
 */
export default function LoopEvidencePanel({ loops }: { loops: LoopDefinition[] }) {
  const loaded = loops.length > 0;
  const totalGates = loops.reduce((sum, loop) => sum + loop.policy_gates.length, 0);
  const totalFailureModes = loops.reduce((sum, loop) => sum + loop.failure_modes.length, 0);

  return (
    <MetricGrid className="lg:grid-cols-3 xl:grid-cols-3">
      <MetricCard
        label="Defined loops"
        value={loaded ? loops.length : null}
        hint="Typed loops the runtime models"
      />
      <MetricCard
        label="Policy gates"
        value={loaded ? totalGates : null}
        hint="Declared across all loop definitions"
      />
      <MetricCard
        label="Failure modes modeled"
        value={loaded ? totalFailureModes : null}
        hint="Each with a declared fallback behaviour"
      />
    </MetricGrid>
  );
}
