import type { DefaultSession } from "next-auth";

/**
 * The three fields every downstream consumer reads. Whatever identity provider is
 * plugged in, the `jwt` callback in auth.ts is responsible for populating these —
 * nothing else in the app should reach for provider-specific claims.
 */
declare module "next-auth" {
  interface Session {
    user: {
      tenantId?: string;
      memoryopsUserId?: string;
      role?: string;
    } & DefaultSession["user"];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    tenantId?: string;
    memoryopsUserId?: string;
    role?: string;
  }
}
