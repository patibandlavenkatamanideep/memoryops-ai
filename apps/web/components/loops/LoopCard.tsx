"use client";

import { LoopDefinition } from "@/lib/api";
import { Badge, FieldLabel, Panel, PanelBody, cn } from "@/components/ui";

/**
 * One loop definition, selectable.
 *
 * This is a real `<button>` rather than a card wrapped in one: the previous version
 * nested a styled article inside `<button className="text-left">`, which gave no
 * focus treatment and no indication of which loop was currently selected.
 */
export default function LoopCard({
  loop,
  selected = false,
  onSelect,
}: {
  loop: LoopDefinition;
  selected?: boolean;
  onSelect?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className="w-full rounded-panel text-left"
    >
      <Panel
        as="div"
        tone={selected ? "accent" : "default"}
        className={cn(
          "h-full transition-colors",
          selected ? "bg-accent/5" : "hover:bg-surface-raised",
        )}
      >
        <PanelBody className="space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h3 className="text-sm font-semibold text-fg">{loop.name}</h3>
            <Badge tone={selected ? "accent" : "quiet"} mono>
              {loop.id}
            </Badge>
          </div>
          <p className="text-xs leading-relaxed text-fg-secondary">{loop.purpose}</p>
          <p className="text-xs text-fg-muted">Trigger: {loop.trigger}</p>
          <div className="space-y-1.5">
            <FieldLabel>Evidence required</FieldLabel>
            <div className="flex flex-wrap gap-1.5">
              {loop.evidence_required.map((item) => (
                <Badge key={item} tone="quiet">
                  {item}
                </Badge>
              ))}
            </div>
          </div>
        </PanelBody>
      </Panel>
    </button>
  );
}
