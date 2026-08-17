import { afterEach, describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { config, isPublicPath, middleware } from "@/middleware";

/**
 * The web's public/protected route boundary.
 *
 * v2.6 Stage B makes `/` a public landing surface. That is an authorization
 * boundary change, and the failure mode it invites is severe and quiet: public
 * paths used to be matched with a bare `pathname.startsWith(p)`, under which the
 * single character `/` is a prefix of *every* route. Adding it to that list would
 * have made the entire control plane anonymous without naming a single one of
 * those routes in the diff, and no existing test would have noticed.
 *
 * So the matrix below is asserted route by route rather than by re-deriving the
 * rule the implementation uses. These tests are deliberately dumb: they encode
 * the intended answer for each path, so a change to the matching strategy has to
 * survive the list.
 *
 * Scope: this is the human-redirect layer only. It is not the security boundary —
 * the BFF re-resolves identity server-side on every API call and is covered by
 * lib/__tests__/scope.test.ts and lib/__tests__/capabilities.test.ts.
 */

const AUTHENTICATED = "authenticated";

/** Routes reachable with no session, by deliberate decision. */
const PUBLIC_ROUTES = ["/", "/signin", "/architecture"];

/**
 * Application surfaces. Every one must redirect an anonymous visitor.
 * `/memories/[id]` is included concretely: a nested dynamic route is exactly the
 * shape a prefix-matching mistake would leak.
 */
const PROTECTED_ROUTES = [
  "/chat",
  "/memories",
  "/memories/mem_01H8XYZ",
  "/governance",
  "/audit",
  "/loops",
  "/admin",
];

function request(pathname: string, { session = false } = {}) {
  const headers = new Headers();
  if (session) headers.set("cookie", "authjs.session-token=stub-session-value");
  return new NextRequest(new URL(pathname, "https://control.example.com"), { headers });
}

/** Middleware returns a plain `NextResponse.next()` when it lets a request through. */
function isPassThrough(response: Response): boolean {
  return response.status === 200 && response.headers.get("location") === null;
}

afterEach(() => {
  delete process.env.MEMORYOPS_WEB_MODE;
});

describe("authenticated mode — anonymous visitor", () => {
  for (const route of PUBLIC_ROUTES) {
    it(`serves ${route} without a session`, () => {
      process.env.MEMORYOPS_WEB_MODE = AUTHENTICATED;
      expect(isPassThrough(middleware(request(route)))).toBe(true);
    });
  }

  for (const route of PROTECTED_ROUTES) {
    it(`redirects ${route} to sign-in without a session`, () => {
      process.env.MEMORYOPS_WEB_MODE = AUTHENTICATED;
      const response = middleware(request(route));

      expect(response.status).toBe(307);
      const location = new URL(response.headers.get("location") ?? "");
      expect(location.pathname).toBe("/signin");
      // The visitor must land back where they were going, not on the home page.
      expect(location.searchParams.get("callbackUrl")).toBe(route);
    });
  }

  it("keeps the Auth.js callback subtree reachable", () => {
    process.env.MEMORYOPS_WEB_MODE = AUTHENTICATED;
    for (const route of [
      "/api/auth",
      "/api/auth/csrf",
      "/api/auth/session",
      "/api/auth/callback/credentials",
    ]) {
      expect(isPassThrough(middleware(request(route))), route).toBe(true);
    }
  });

  it("protects the BFF proxy, which is not part of the public surface", () => {
    process.env.MEMORYOPS_WEB_MODE = AUTHENTICATED;
    expect(middleware(request("/api/memoryops/api/memories")).status).toBe(307);
  });
});

describe("authenticated mode — with a session cookie", () => {
  it("serves every application route", () => {
    process.env.MEMORYOPS_WEB_MODE = AUTHENTICATED;
    for (const route of [...PUBLIC_ROUTES, ...PROTECTED_ROUTES]) {
      expect(
        isPassThrough(middleware(request(route, { session: true }))),
        route,
      ).toBe(true);
    }
  });

  it("accepts the __Secure- cookie name used over HTTPS", () => {
    process.env.MEMORYOPS_WEB_MODE = AUTHENTICATED;
    const headers = new Headers({
      cookie: "__Secure-authjs.session-token=stub-session-value",
    });
    const secure = new NextRequest(new URL("/chat", "https://control.example.com"), {
      headers,
    });
    expect(isPassThrough(middleware(secure))).toBe(true);
  });
});

describe("demo mode", () => {
  it("does not redirect anything — the public demo has no sign-in", () => {
    process.env.MEMORYOPS_WEB_MODE = "demo";
    for (const route of [...PUBLIC_ROUTES, ...PROTECTED_ROUTES]) {
      expect(isPassThrough(middleware(request(route))), route).toBe(true);
    }
  });

  it("treats an unset mode as not-authenticated, matching lib/identity's default", () => {
    for (const route of PROTECTED_ROUTES) {
      expect(isPassThrough(middleware(request(route))), route).toBe(true);
    }
  });
});

describe("isPublicPath fails closed", () => {
  it("does not let `/` act as a prefix for anything", () => {
    // The single assertion this whole stage exists to guarantee.
    for (const route of PROTECTED_ROUTES) {
      expect(isPublicPath(route), route).toBe(false);
    }
  });

  it("does not treat a longer path as a public one it merely starts with", () => {
    for (const route of [
      "/architecture-internal",
      "/architecturex",
      "/signin-as-admin",
      "/signinx",
      "/api/authz",
    ]) {
      expect(isPublicPath(route), route).toBe(false);
    }
  });

  it("refuses dot segments, literal or percent-encoded", () => {
    // `new URL()` resolves literal `..` but leaves `%2e%2e` alone, so a path could
    // otherwise satisfy a public prefix while routing somewhere else.
    for (const route of [
      "/architecture/%2e%2e/chat",
      "/architecture/%2E%2E/admin",
      "/architecture/../chat",
      "/signin/%2e%2e/memories",
    ]) {
      expect(isPublicPath(route), route).toBe(false);
    }
  });

  it("handles trailing slashes without widening the public surface", () => {
    // `/architecture/` is the same resource as `/architecture` — Next redirects it
    // there — so it stays public. What matters is that a trailing slash cannot
    // turn a protected route into a public one.
    expect(isPublicPath("/architecture/")).toBe(true);
    for (const route of PROTECTED_ROUTES) {
      expect(isPublicPath(`${route}/`), `${route}/`).toBe(false);
    }
  });

  it("recognises exactly the three intended public surfaces", () => {
    for (const route of PUBLIC_ROUTES) {
      expect(isPublicPath(route), route).toBe(true);
    }
  });
});

describe("matcher coverage", () => {
  it("excludes only build assets, so no application route escapes the guard", () => {
    // A broadened exclusion here would unprotect routes without touching any of
    // the logic above, and nothing else in the suite would fail.
    expect(config.matcher).toEqual(["/((?!_next/static|_next/image|favicon.ico).*)"]);
  });

  it("matches every protected route", () => {
    const [pattern] = config.matcher;
    const matcher = new RegExp(`^${pattern}$`);
    for (const route of PROTECTED_ROUTES) {
      expect(matcher.test(route), route).toBe(true);
    }
  });
});
