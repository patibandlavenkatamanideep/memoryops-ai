# Governance UI (v2.6)

The browser-facing control plane for MemoryOps' governed memory lifecycle. It
makes the lifecycle **operable by a human** without weakening any invariant —
every view is tenant-scoped and every action is audited. See
[ADR-009](../infra/adr/ADR-009-memory-control-plane.md) and the companion
[memory-control-plane.md](memory-control-plane.md).

## Pages

| Route | Purpose |
| --- | --- |
| `/memories` | Filterable memory inventory (search + status + type). Soft-deleted rows are never listed. |
| `/memories/[id]` | Detail: content (inline edit), lifecycle actions, provenance/explainability, per-memory audit timeline. |
| `/governance` | Human-in-the-loop approval queue + recent policy-broker decisions. |
| `/audit` | Tenant-wide append-only audit history, newest first. |

## Components

- `components/memories/`
  - `MemoryTable` — the inventory in two presentations of the same records: a
    dense eight-column table at `md` and wider, and a card list below it. The
    table needs ~40rem, so on a 390px viewport Status and Actions sat roughly
    600px inside a horizontal scroll region the operator had no reason to know
    existed. The card carries every field the row does — content, type,
    sensitivity, importance, confidence, status, source and the same actions — so
    it is a reflow, not a mobile-only subset, and only one presentation is in the
    accessibility tree at a time.
  - `MemoryFilters` — search + status + type filters (`deleted` is intentionally
    not selectable — it is never part of the active inventory).
  - `MemoryDetailPanel` — self-fetching detail (memory + provenance + audit),
    inline content edit.
  - `MemoryProvenance` — source/provenance and the durable ranking signals that
    explain why a memory is used.
  - `MemoryActions` — approve / reject / archive / restore / delete. Each maps to
    an audited backend route; deleted memories expose no actions.
- `components/governance/`
  - `PendingMemoryQueue` — the approval queue (approve/reject).
  - `PolicyDecisionCard` — renders one recorded policy decision (SAVE / PENDING /
    BLOCKED / DROPPED / UPDATED / MERGED) with its rationale.
- `components/audit/`
  - `AuditTimeline` — reusable append-only timeline (used on detail and `/audit`).
- `components/ui/`, `components/shell/` — the shared design system and application
  shell every surface above composes. See
  [Design system and shell (v2.6)](#design-system-and-shell-v26).

## Action → backend mapping

| UI action | Backend call | Audit action |
| --- | --- | --- |
| approve | `PATCH /api/memories/{id}` `status=active` | `memory_approved` |
| reject | `PATCH /api/memories/{id}` `status=rejected` | `memory_rejected` |
| archive | `PATCH /api/memories/{id}` `status=archived` | `memory_archived` |
| restore | `PATCH /api/memories/{id}` `status=active` | `memory_approved` |
| edit | `PATCH /api/memories/{id}` `content=…` | `memory_updated` |
| delete | `DELETE /api/memories/{id}` | `memory_deleted` |

## Safety properties

- **Deletion guarantee** — deleted memories never appear in the inventory and are
  never rendered as active; the terminal `deleted` status carries on the record.
- **Tenant isolation** — all reads/writes are tenant + user scoped.
- **Auditability** — every action appends an audit event; the timeline reflects it.
- **Policy authority** — the UI only displays decisions the broker already made;
  it never writes around the policy/write path.
- **No secret leakage** — provenance is metadata only; no embeddings or secrets.

## Identity

Identity is resolved **server-side only**, by `apps/web/lib/identity.ts`, and is
never accepted from the client. `lib/api.ts` carries no tenant/user argument at
all; the BFF (`app/api/memoryops/[...path]/route.ts`) strips any scope the browser
supplied and substitutes the server-resolved values. In demo mode that is the
shared `tenant_demo` / `user_demo` persona, labelled as such by `ModeBanner`; in
`authenticated` mode it comes from the Auth.js session, and a missing session
fails closed rather than falling back to the demo identity.

The shell surfaces that scope in the sidebar footer and top bar, so which tenant
an operator is acting on never has to be inferred from the data on screen. That
display is a plain projection (`ShellIdentity`) carrying no credential and no
capability set — the BFF re-decides every request regardless.

## Design system and shell (v2.6)

Before v2.6 each surface restyled itself: colours were re-picked at the call
site, there were several competing status-badge maps, and nothing guaranteed a
contrast floor or a consistent focus treatment.

- `apps/web/app/globals.css` declares the design tokens once, as space-separated
  RGB channels so Tailwind's `<alpha-value>` modifier works against them. Four
  elevation tiers, two border weights, a three-step foreground ramp whose lowest
  step still clears 4.5:1 on `surface`, and semantic status hues.
- `apps/web/tailwind.config.ts` resolves those variables into semantic utilities
  and contains no literal colour, so the token file stays the only place a colour
  is decided.
- `apps/web/components/ui/` holds the first-party primitives — `Panel`, `Button`,
  `Badge`/`StatusBadge`, `DataTable`, form controls, `PageHeader`/`SectionHeader`,
  `MetricCard`, `Timeline`, `DetailPanel`/`Disclosure`/`EvidenceBlock`, the
  empty/loading/error states, and value treatments (`Code`, `MonoId`, `KeyValue`,
  `ScoreBar`). No UI framework or icon package was introduced.
- `apps/web/components/shell/` holds `AppShell` (fixed sidebar on desktop,
  off-canvas drawer below `lg`), `SidebarNav`, `TopBar` and the navigation model.

Lifecycle status → badge tone now lives in one place (`components/ui/Badge.tsx`,
`MEMORY_STATUS_TONE` / `RUN_STATUS_TONE`), replacing the former
`components/memories/statusStyles.ts`. An unrecognised status resolves to a
neutral tone, never a success one, and `deleted` is de-toned **and** struck
through — colour alone is not perceivable to every operator, and invariant #2 is
the one state that must never be presented as active.

### `navigation.ts` is presentation, not authorization

`components/shell/navigation.ts` declares what the rail, the drawer and the top
bar's section label show. Adding an entry grants no access and removing one
protects nothing: page navigation is gated by `apps/web/middleware.ts` and every
API call by the BFF's `canAttempt()` check. `/signin` renders without chrome
because a rail of sections the visitor cannot open yet is noise — hiding chrome
is a usability decision, exactly as hiding a control is.

### Accessibility floor

Applies to every surface, enforced by the primitives rather than per page:

- one `:focus-visible` ring for the whole app, defined with the token set;
- a skip link as the first focusable element, and `aria-current="page"` on the
  active section;
- exactly one `<main id="main-content">` per page, owned by whichever shell
  actually wraps the route. `AppShell`'s chromeless branch emits none, because a
  chromeless route supplies its own — when both emitted one, `/` shipped nested
  `<main>` elements and a duplicate id, and the skip link resolved to the outer
  wrapper instead of the content;
- the mobile navigation drawer traps Tab while open and returns focus to the
  control that opened it. `aria-modal` marks the background inert for assistive
  tech but moves no focus, so without a trap an operator could tab onto — and
  activate — a destructive control the scrim was covering. Restoration happens at
  the point of dismissal, not in an effect cleanup, because by cleanup time the
  panel is unmounted and focus has fallen to `<body>`; following a nav link
  deliberately does not restore, since the destination decides where focus goes;
- every primitive that renders verbatim server text (`SourceQuote`, `KeyValue`,
  `TimelineItem`, `ErrorState`) declares a wrapping rule. Provenance excerpts and
  audit reasons routinely carry a URL or an opaque identifier with no break
  opportunity, and such a token paints past its container and grows the document
  while every element still reports itself in bounds — `/memories/{id}` carried
  78px of horizontal overflow at 360px before this was found;
- form controls labelled by wrapping — no generated id to drift or lose, and no
  placeholder standing in for a label;
- tables as labelled, focusable scroll regions with real `<th scope="col">`, so
  overflowing columns are reachable by keyboard and not only by trackpad;
- loading announced with `role="status"`, failures with `role="alert"`;
- `prefers-reduced-motion` respected globally.

Every token pair used for text measures at or above WCAG AA (4.5:1) on its
surface; the lowest is `fg-muted` on `surface-raised` at 4.85:1.

Verified by driving the built app in a real browser (system Chrome over CDP, no
browser dependency in the repo) at 360 / 390 / 768 / 1024 / 1440 / 1920 against a
live API with seeded data: 0px horizontal overflow on every route, a focus ring on
every tab stop, the skip link first in tab order, 0 console errors and 0 hydration
mismatches, and every animation and transition clamped under
`prefers-reduced-motion: reduce`.

One accepted limitation: `/loops` still scrolls its four-column run table
horizontally at 360-390px. The columns are informational, no control is stranded,
and the scroll region is labelled and keyboard-reachable, so it is recorded rather
than reflowed.

### Real state only

Empty datasets render an explanation of why they are empty and what fills them,
never sample rows. A metric that has not loaded renders as pending rather than as
`0` — on an operations surface, "none happened" and "we could not ask" must not
look identical. Statements about the codebase (RLS enforcement, release gates) are
prose, not metric cards, so they cannot read as counters that are always healthy.

## Control visibility is generated, not ranked (v2.4)

The UI used to decide what to show from a persona ladder —
`viewer < developer < auditor < memory_admin < owner` — and the BFF used the same
ranking to decide what to proxy. Ranks cannot express the API's model, where
capabilities are orthogonal: `memory_admin` outranked `auditor` and so passed every
auditor check, while holding no `evidence:read` at the API at all.

`apps/web/lib/authzCapabilities.generated.ts` is generated from the API's own
`ROUTE_AUTHZ` and `ROLE_PERMISSIONS`, and `uiCapabilities()` derives control
visibility from it — every field is a real `canAttempt()` call against the route the
control invokes. There is no component-level role table, so an affordance cannot claim
a capability the proxy would refuse.

| Persona | Sees |
| --- | --- |
| viewer | its own memory, read-only |
| developer | chat, edit, archive/restore, delete — its own |
| auditor | audit, evidence, governance timelines; **no** mutation controls |
| memory_admin | tenant lifecycle, approve/reject, retention, consent; **no** evidence |
| owner | every tenant control; **no** deployment operations |

### Hiding a control is usability, not security

`MemoryActions` accepts an optional `capabilities` prop. Omitting it renders every
control and lets the server decide — the pre-existing behaviour, and still safe: the
BFF refuses independently and the API refuses again after loading the record.

The web answers *may this persona attempt this shape*, never *is this authorized on
this record*. The browser does not know a memory's stored owner, whether a request
resolves to self or tenant scope, or the record's current lifecycle status — which is
why `status: "active"` is treated as approve-**or**-restore and left to the API.

