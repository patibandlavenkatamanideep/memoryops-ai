import { defineConfig } from "vitest/config";

/**
 * Unit tests for the web app's security-relevant pure logic: BFF scope
 * sanitisation and the role model. Deliberately node-only and fast — no Next.js
 * runtime, no DOM, no network. The modules under test (lib/scope.ts, lib/roles.ts)
 * are kept free of `server-only` and NextAuth imports precisely so they can be
 * exercised directly rather than through a mocked framework.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["lib/__tests__/**/*.test.ts"],
  },
});
