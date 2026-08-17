import type { NavGlyph } from "./navigation";

/**
 * Navigation glyphs.
 *
 * Hand-drawn 16px strokes rather than an icon package. A dependency here would pull a
 * few thousand icons (and its own release cadence, licence and bundle) to render the
 * eight marks this app actually uses — and MemoryOps wants its own visual identity
 * more than it wants a familiar icon set.
 *
 * All glyphs share one grid, one 1.5 stroke width and `currentColor`, so they inherit
 * the nav link's active/muted state instead of carrying colour of their own. They are
 * decorative: every link has a text label, so the SVG is `aria-hidden`.
 */
const PATHS: Record<NavGlyph, React.ReactNode> = {
  // Four panes — the whole surface at a glance.
  overview: (
    <>
      <rect x="2.5" y="2.5" width="4.5" height="4.5" rx="1" />
      <rect x="9" y="2.5" width="4.5" height="4.5" rx="1" />
      <rect x="2.5" y="9" width="4.5" height="4.5" rx="1" />
      <rect x="9" y="9" width="4.5" height="4.5" rx="1" />
    </>
  ),
  // A turn of conversation.
  chat: (
    <>
      <path d="M2.5 4.5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H6l-3.5 3v-3z" />
    </>
  ),
  // Stacked records.
  memories: (
    <>
      <path d="M8 2.5 14 5.5 8 8.5 2 5.5z" />
      <path d="M2 8.5 8 11.5 14 8.5" />
      <path d="M2 11.5 8 14.5 14 11.5" />
    </>
  ),
  // Policy shield — the write path's choke point.
  governance: (
    <>
      <path d="M8 2 13 4v4c0 3-2.2 5.2-5 6-2.8-.8-5-3-5-6V4z" />
      <path d="M5.75 8.1 7.3 9.6l3-3.2" />
    </>
  ),
  // Ledger lines with a seal.
  audit: (
    <>
      <path d="M3 3.5h10M3 6.5h10M3 9.5h6M3 12.5h4" />
      <circle cx="11.5" cy="11.5" r="2.5" />
    </>
  ),
  // A closed cycle.
  loops: (
    <>
      <path d="M13 8a5 5 0 1 1-1.8-3.85" />
      <path d="M13.2 2.2v2.6h-2.6" />
    </>
  ),
  // Operational controls.
  admin: (
    <>
      <path d="M2.5 5h11M2.5 11h11" />
      <circle cx="6" cy="5" r="1.75" />
      <circle cx="10.5" cy="11" r="1.75" />
    </>
  ),
  // Connected components.
  architecture: (
    <>
      <circle cx="8" cy="3.5" r="1.75" />
      <circle cx="3.5" cy="12.5" r="1.75" />
      <circle cx="12.5" cy="12.5" r="1.75" />
      <path d="M6.9 4.9 4.6 10.9M9.1 4.9l2.3 6M5.25 12.5h5.5" />
    </>
  ),
};

export default function NavIcon({ glyph }: { glyph: NavGlyph }) {
  return (
    <svg
      aria-hidden
      focusable="false"
      viewBox="0 0 16 16"
      className="h-4 w-4 shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {PATHS[glyph]}
    </svg>
  );
}
