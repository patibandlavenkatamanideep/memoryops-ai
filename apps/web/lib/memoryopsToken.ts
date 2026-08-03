import "server-only";

import { SignJWT } from "jose";

import type { Identity } from "@/lib/identity";

/**
 * Mints the short-lived credential the BFF presents to the MemoryOps API.
 *
 * The browser never sees this token. It exists only on the server hop between the
 * Next.js route handler and the API, which is why it can be short-lived and why no
 * API credential needs to be exposed through `NEXT_PUBLIC_*`.
 *
 * Claim shape matches the API's JWT adapter defaults
 * (`auth_jwt_tenant_claim=tenant_id`, `auth_jwt_user_claim=sub`) — see
 * services/api/app/auth/providers.py and docs/auth-adapters.md.
 */

const DEFAULT_TTL_SECONDS = 120;

export type ApiCredential =
  | { kind: "jwt"; token: string }
  | { kind: "trusted_header" }
  | { kind: "none" };

function secret(): Uint8Array | null {
  const key = process.env.MEMORYOPS_AUTH_JWT_KEY;
  if (!key) return null;
  return new TextEncoder().encode(key);
}

export async function mintApiToken(identity: Identity): Promise<string | null> {
  const key = secret();
  if (!key) return null;

  const ttl = Number(process.env.MEMORYOPS_API_TOKEN_TTL_SECONDS ?? DEFAULT_TTL_SECONDS);
  const builder = new SignJWT({
    tenant_id: identity.tenantId,
    // `roles` (plural, array) is what the API's adapter reads by default. Emitting
    // a singular `role` meant the claim never matched, so every authenticated web
    // user — including auditors and admins — reached the API with no recognised
    // role and fell back to the least-privileged default.
    roles: [identity.role],
  })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(identity.userId)
    .setIssuedAt()
    .setExpirationTime(`${Number.isFinite(ttl) && ttl > 0 ? ttl : DEFAULT_TTL_SECONDS}s`);

  const audience = process.env.MEMORYOPS_AUTH_JWT_AUDIENCE;
  const issuer = process.env.MEMORYOPS_AUTH_JWT_ISSUER;
  if (audience) builder.setAudience(audience);
  if (issuer) builder.setIssuer(issuer);

  return builder.sign(key);
}

/**
 * Chooses how to authenticate to the API, mirroring `MEMORYOPS_AUTH_MODE`.
 *
 * `none` is legitimate for local development against a dev-profile API, but the
 * production profile rejects it at startup, so a production deployment must set
 * one of the other two.
 */
export async function apiCredential(identity: Identity): Promise<ApiCredential> {
  const mode = process.env.MEMORYOPS_AUTH_MODE ?? "none";
  if (mode === "jwt") {
    const token = await mintApiToken(identity);
    if (!token) {
      throw new Error(
        "MEMORYOPS_AUTH_MODE=jwt but MEMORYOPS_AUTH_JWT_KEY is unset — refusing to " +
          "call the API unauthenticated",
      );
    }
    return { kind: "jwt", token };
  }
  if (mode === "trusted_header") return { kind: "trusted_header" };
  return { kind: "none" };
}
