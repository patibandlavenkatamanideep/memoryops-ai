/**
 * The control-plane design system.
 *
 * One import site so a surface picks up primitives rather than re-deriving spacing,
 * borders and status colours per page. Everything here is first-party and
 * Tailwind-only — no component library was introduced, because the token set in
 * app/globals.css is what makes these consistent, not the library they came from.
 */

export { cn, type ClassValue } from "./cn";

export { Button, type ButtonProps, type ButtonSize, type ButtonVariant } from "./Button";

export {
  Badge,
  StatusBadge,
  MEMORY_STATUS_TONE,
  RUN_STATUS_TONE,
  toneForMemoryStatus,
  toneForRunStatus,
  type Tone,
} from "./Badge";

export { DataTable, TBody, TD, TH, THead, TR, TableEmptyRow } from "./DataTable";

export { DetailPanel, Disclosure, EvidenceBlock } from "./DetailPanel";

export { Checkbox, Field, Select, TextArea, TextInput, Toolbar } from "./Form";

export { FieldLabel, PageHeader, SectionHeader } from "./Headers";

export { MetricCard, MetricGrid } from "./MetricCard";

export {
  Panel,
  PanelBody,
  PanelFooter,
  PanelHeader,
  type PanelTone,
} from "./Panel";

export { EmptyState, ErrorState, LoadingState, Skeleton } from "./States";

export { Timeline, TimelineItem } from "./Timeline";

export { Code, DefinitionList, KeyValue, MonoId, ScoreBar, SourceQuote } from "./Values";
