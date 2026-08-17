/**
 * The control plane's navigation model.
 *
 * One declaration, consumed by the sidebar, the mobile drawer and the top bar's
 * section label, so those three cannot disagree about what a route is called.
 *
 * This is a *presentation* model only. It says nothing about who may reach a route:
 * access is decided by middleware.ts for page navigation and by the BFF's capability
 * check for every API call. Adding an entry here grants nothing, and removing one
 * protects nothing.
 */

export type NavGlyph =
  | "overview"
  | "chat"
  | "memories"
  | "governance"
  | "audit"
  | "loops"
  | "admin"
  | "architecture";

export interface NavItem {
  readonly href: string;
  readonly label: string;
  /** One line, shown in the mobile drawer and as the link's title. */
  readonly summary: string;
  readonly glyph: NavGlyph;
}

export interface NavGroup {
  readonly label: string;
  readonly items: readonly NavItem[];
}

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    label: "Runtime",
    items: [
      {
        href: "/",
        label: "Overview",
        summary: "What MemoryOps governs and how the lifecycle fits together",
        glyph: "overview",
      },
      {
        href: "/chat",
        label: "Chat",
        summary: "A governed session: candidates, policy decisions, memory used",
        glyph: "chat",
      },
      {
        href: "/memories",
        label: "Memories",
        summary: "Typed memory registry with status, provenance and lifecycle actions",
        glyph: "memories",
      },
    ],
  },
  {
    label: "Governance",
    items: [
      {
        href: "/governance",
        label: "Governance",
        summary: "Approval queue and the policy broker's recorded decisions",
        glyph: "governance",
      },
      {
        href: "/audit",
        label: "Audit",
        summary: "Append-only lifecycle evidence, newest first",
        glyph: "audit",
      },
    ],
  },
  {
    label: "Operations",
    items: [
      {
        href: "/loops",
        label: "Loops",
        summary: "Loop definitions, runs and events for background lifecycle work",
        glyph: "loops",
      },
      {
        href: "/admin",
        label: "Admin",
        summary: "Runtime counters, retrieval and data-layer configuration",
        glyph: "admin",
      },
    ],
  },
  {
    label: "Reference",
    items: [
      {
        href: "/architecture",
        label: "Architecture",
        summary: "Write path, read path and the planes that wrap them",
        glyph: "architecture",
      },
    ],
  },
];

export const NAV_ITEMS: readonly NavItem[] = NAV_GROUPS.flatMap((g) => g.items);

/**
 * Is `href` the section the current path belongs to?
 *
 * `/` matches only exactly — a prefix test would light up Overview on every page.
 * Everything else matches its subtree so `/memories/{id}` keeps Memories selected.
 */
export function isActivePath(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The nav entry owning the current path, if any. Used for the top bar's label. */
export function activeNavItem(pathname: string): NavItem | undefined {
  // Longest href first so `/memories/{id}` resolves to Memories, not Overview.
  return [...NAV_ITEMS]
    .sort((a, b) => b.href.length - a.href.length)
    .find((item) => isActivePath(pathname, item.href));
}

/**
 * Routes that render without the control-plane chrome.
 *
 * Presentation only. `/signin` is the one surface where a sidebar full of links the
 * visitor cannot yet open would be noise rather than navigation.
 */
const CHROMELESS_PREFIXES = ["/signin"] as const;

export function isChromeless(pathname: string): boolean {
  return CHROMELESS_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}
