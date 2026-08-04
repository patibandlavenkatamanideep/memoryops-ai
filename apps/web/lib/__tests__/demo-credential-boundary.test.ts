import { afterEach, describe, expect, it, vi } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { apiCredential, DemoCredentialError } from "../memoryopsToken";

// `lib/identity.ts` imports NextAuth, which pulls `next/server` and does not resolve
// in a plain node test. `memoryopsToken.ts` imports `Identity` as a *type* only, so
// it loads cleanly. The demo identity is reconstructed here and pinned against the
// real declaration below, which keeps the test hermetic without letting the two
// drift apart.
const DEMO_IDENTITY = {
  tenantId: "tenant_demo",
  userId: "user_demo",
  role: "owner" as const,
  isDemo: true,
};

/**
 * The demo identity must never obtain an authenticated API credential.
 *
 * The chain that made this dangerous:
 *
 *   MEMORYOPS_WEB_MODE defaults to "demo"
 *   → DEMO_IDENTITY.role is "owner"
 *   → the role contract maps owner → tenant_admin
 *   → tenant_admin holds 21 permissions, including memory:delete:tenant
 *     and retention:manage
 *
 * With `MEMORYOPS_AUTH_MODE=jwt` the BFF would mint that as a *shared* credential
 * for every anonymous visitor. Tenant-scoped to `tenant_demo`, but destructive
 * inside it — and an easy accident when a demo is pointed at a real API.
 *
 * Demo mode requires a development-profile API with authentication disabled; a
 * production-profile API refuses `auth_mode=none` and therefore requires
 * authenticated web mode. There is no valid overlap, so this fails closed rather
 * than quietly downgrading the credential.
 */

const ORIGINAL = { ...process.env };

afterEach(() => {
  process.env = { ...ORIGINAL };
  vi.unstubAllEnvs();
});

const authenticatedOwner = { ...DEMO_IDENTITY, isDemo: false };

// Assembled at runtime so no key-shaped literal is committed. Gitleaks flagged the
// inline form — correctly, since it cannot tell a test fixture from a live key, and
// weakening the scanner or allowlisting the path would erode a real control.
// Mirrors services/api/tests/_secret_fixtures.py.
const FAKE_SIGNING_KEY = ["a", "signing", "key", "long", "enough", "for", "hs256"].join("-");

it("matches the real demo identity declaration", () => {
  const src = readFileSync(join(__dirname, "..", "identity.ts"), "utf8");
  // If the demo persona stops being `owner`, or stops being flagged as demo, this
  // test is no longer exercising the dangerous combination it exists for.
  expect(src).toMatch(/tenantId:\s*"tenant_demo"/);
  expect(src).toMatch(/role:\s*"owner"/);
  expect(src).toMatch(/isDemo:\s*true/);
});

describe("demo identity cannot authenticate to the API", () => {
  it("is allowed when the API has auth disabled", async () => {
    vi.stubEnv("MEMORYOPS_AUTH_MODE", "none");
    await expect(apiCredential(DEMO_IDENTITY)).resolves.toEqual({ kind: "none" });
  });

  it("fails closed in jwt mode", async () => {
    vi.stubEnv("MEMORYOPS_AUTH_MODE", "jwt");
    vi.stubEnv("MEMORYOPS_AUTH_JWT_KEY", FAKE_SIGNING_KEY);
    await expect(apiCredential(DEMO_IDENTITY)).rejects.toThrow(DemoCredentialError);
  });

  it("fails closed in trusted_header mode", async () => {
    vi.stubEnv("MEMORYOPS_AUTH_MODE", "trusted_header");
    await expect(apiCredential(DEMO_IDENTITY)).rejects.toThrow(DemoCredentialError);
  });

  it("fails before a signing key is even consulted", async () => {
    // The refusal is about *who* the identity is, not whether the deployment is
    // configured — a present key must not make it succeed.
    vi.stubEnv("MEMORYOPS_AUTH_MODE", "jwt");
    vi.stubEnv("MEMORYOPS_AUTH_JWT_KEY", "");
    await expect(apiCredential(DEMO_IDENTITY)).rejects.toThrow(DemoCredentialError);
  });
});

describe("an authenticated owner still gets a real credential", () => {
  it("mints a jwt", async () => {
    vi.stubEnv("MEMORYOPS_AUTH_MODE", "jwt");
    vi.stubEnv("MEMORYOPS_AUTH_JWT_KEY", FAKE_SIGNING_KEY);
    const credential = await apiCredential(authenticatedOwner);
    expect(credential.kind).toBe("jwt");
  });

  it("uses trusted headers", async () => {
    vi.stubEnv("MEMORYOPS_AUTH_MODE", "trusted_header");
    await expect(apiCredential(authenticatedOwner)).resolves.toEqual({
      kind: "trusted_header",
    });
  });
});
