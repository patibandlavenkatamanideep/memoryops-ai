/**
 * Conditional class joiner.
 *
 * Deliberately not `clsx`/`tailwind-merge`: the whole need here is "drop falsy
 * entries and join", which is four lines. A dependency for that is supply-chain
 * surface for no capability.
 *
 * It does not de-duplicate conflicting Tailwind classes — components take the caller's
 * `className` last so the caller wins by CSS order, and variants are built from
 * disjoint class sets rather than by overriding each other.
 */
export type ClassValue = string | false | null | undefined;

export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}
