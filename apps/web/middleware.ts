import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Route guard for the authenticated control plane.
 *
 * In `MEMORYOPS_WEB_MODE=authenticated`, every application surface requires a
 * session cookie. This is a fast redirect for humans, not the security boundary —
 * the real enforcement is in the BFF (`app/api/memoryops/[...path]`), which
 * re-resolves identity server-side on every API call and returns 401/403.
 * Middleware alone must never be relied on for authorization.
 *
 * In demo mode this is a no-op so the public demo keeps working unauthenticated.
 */

/**
 * Public surfaces matched **exactly**.
 *
 * `/` lives here and must never move into `PUBLIC_PREFIXES`. The previous
 * implementation tested every public path with a bare
 * `pathname.startsWith(p)` — under that rule the single character `/` is a prefix
 * of every path in the application, so listing it would have silently made
 * `/chat`, `/memories`, `/governance`, `/audit`, `/loops` and `/admin` public in
 * one line, with nothing in the diff naming those routes. Exact matching is what
 * makes the landing page public without touching anything else.
 */
const PUBLIC_EXACT = new Set(["/"]);

/**
 * Public subtrees, matched as the path itself or a `/`-delimited descendant.
 *
 * `/api/auth` needs subtree access for the Auth.js callback, CSRF and session
 * endpoints. `/signin` and `/architecture` have no children today and are listed
 * here so that adding one later does not require a second rule.
 */
const PUBLIC_PREFIXES = ["/signin", "/api/auth", "/architecture"];

/**
 * Dot segments, literal or percent-encoded.
 *
 * `new URL()` resolves literal `..` before `nextUrl.pathname` is read, but it does
 * not decode `%2e%2e` — so `/architecture/%2e%2e/chat` would satisfy a
 * `startsWith("/architecture/")` test while routing somewhere else entirely. Such
 * a path is never legitimate here (no MemoryOps route contains a dot segment), so
 * it is refused public status outright rather than normalised and re-checked.
 */
const DOT_SEGMENT = /(^|\/|%2f)(\.|%2e){1,2}($|\/|%2f)/i;

/** Is this path served without a session? Fails closed on anything unrecognised. */
export function isPublicPath(pathname: string): boolean {
  if (DOT_SEGMENT.test(pathname)) return false;
  if (PUBLIC_EXACT.has(pathname)) return true;
  return PUBLIC_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
}

export function middleware(request: NextRequest) {
  if (process.env.MEMORYOPS_WEB_MODE !== "authenticated") return NextResponse.next();

  const { pathname } = request.nextUrl;
  if (isPublicPath(pathname)) return NextResponse.next();

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
