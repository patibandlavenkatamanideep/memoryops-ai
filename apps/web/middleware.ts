import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Route guard for the authenticated control plane.
 *
 * In `MEMORYOPS_WEB_MODE=authenticated`, every page except the sign-in flow
 * requires a session cookie. This is a fast redirect for humans, not the security
 * boundary — the real enforcement is in the BFF (`app/api/memoryops/[...path]`),
 * which re-resolves identity server-side on every API call and returns 401/403.
 * Middleware alone must never be relied on for authorization.
 *
 * In demo mode this is a no-op so the public demo keeps working unauthenticated.
 */

const PUBLIC_PATHS = ["/signin", "/api/auth", "/architecture"];

export function middleware(request: NextRequest) {
  if (process.env.MEMORYOPS_WEB_MODE !== "authenticated") return NextResponse.next();

  const { pathname } = request.nextUrl;
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) return NextResponse.next();

  // Presence check only — the cookie's signature is verified server-side by
  // Auth.js when the BFF calls `auth()`. A forged cookie gets past this redirect
  // and is then rejected with a 401 by the BFF.
  const hasSession =
    request.cookies.has("authjs.session-token") ||
    request.cookies.has("__Secure-authjs.session-token");

  if (!hasSession) {
    const signIn = new URL("/signin", request.url);
    signIn.searchParams.set("callbackUrl", pathname);
    return NextResponse.redirect(signIn);
  }
  return NextResponse.next();
}

export const config = {
  // Skip static assets and image optimization.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
