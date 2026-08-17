import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

/**
 * Unit tests for the web app's security-relevant logic: BFF scope sanitisation, the
 * role model, the web↔API role contract, the demo credential boundary, and the
 * public/protected route matrix in middleware.ts.
 * Node-only and fast — no Next.js runtime, no DOM, no network.
 */
export default defineConfig({
  resolve: {
    alias: {
      // `server-only` throws on import outside a React Server Component, so a plain
      // node test cannot load a module that imports it. It is a *build-time* guard
      // against bundling server modules into the client, not a runtime contract —
      // stubbing it lets these tests exercise the real code in the environment it
      // actually runs in (the server).
      "server-only": fileURLToPath(new URL("./test/server-only-stub.ts", import.meta.url)),
      // Mirrors the `@/*` path alias in tsconfig.json so server modules resolve the
      // same way they do under Next.js.
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    // `__tests__/` at the root covers modules that do not live under lib/ —
    // middleware.ts is at the app root because Next.js requires it there.
    include: ["lib/__tests__/**/*.test.ts", "__tests__/**/*.test.ts"],
  },
});
