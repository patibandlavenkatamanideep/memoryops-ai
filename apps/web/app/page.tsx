import type { Metadata } from "next";

import { PublicShell } from "@/components/public/PublicShell";
import ArchitecturePreview from "@/components/public/sections/ArchitecturePreview";
import BeforeWith from "@/components/public/sections/BeforeWith";
import Capabilities from "@/components/public/sections/Capabilities";
import DecisionTrace from "@/components/public/sections/DecisionTrace";
import GovernanceSimulator from "@/components/public/sections/GovernanceSimulator";
import Hero from "@/components/public/sections/Hero";
import Lifecycle from "@/components/public/sections/Lifecycle";

/**
 * The public product page.
 *
 * Ordered for a first-time visitor rather than for completeness: state the category
 * (Hero), show one concrete governed decision (DecisionTrace), then explain why the
 * architecture is shaped that way (BeforeWith) and let them try it (Simulator).
 * Lifecycle, Capabilities and Architecture only arrive once someone has a reason to
 * care about the detail.
 *
 * Session-independent by construction. Nothing here imports `lib/api`,
 * `lib/identity` or `auth`, and `__tests__/public-landing-independence.test.ts`
 * walks the whole import graph to keep it that way — a page that is publicly
 * reachable but session-dependent renders an error for exactly the visitors it was
 * opened for, and only in production.
 *
 * It renders its own chrome via `PublicShell`; `AppShell` stands aside for `/`
 * (see `components/shell/navigation.ts`).
 */

export const metadata: Metadata = {
  title: "MemoryOps AI — Govern what AI remembers",
  description:
    "A governed memory layer for AI assistants and agents. Every candidate memory passes a policy decision before it is stored, and every memory that reaches model context leaves an audit record.",
};

export default function Home() {
  return (
    <PublicShell>
      <Hero />
      <DecisionTrace />
      <BeforeWith />
      <GovernanceSimulator />
      <Lifecycle />
      <Capabilities />
      <ArchitecturePreview />
    </PublicShell>
  );
}
