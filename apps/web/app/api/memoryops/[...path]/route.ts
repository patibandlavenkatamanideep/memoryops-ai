import { NextResponse } from "next/server";

import {
  hasAtLeast,
  requiredRole,
  resolveIdentity,
  UnauthenticatedError,
} from "@/lib/identity";
import { apiRoleForWebRole } from "@/lib/apiRoles";
import { apiCredential } from "@/lib/memoryopsToken";
import { stripClientScope, stripScopeFromBody } from "@/lib/scope";

/**
 * Backend-for-frontend proxy: the browser's only route to the MemoryOps API.
 *
 * Everything the UI needs goes through here so that **identity is attached on the
 * server and can never be chosen by the client**. Previously the browser called the
 * API directly with `tenant_id=tenant_demo&user_id=user_demo` baked into the URL or
 * body, which meant the scope was client-controlled request data — editable in
 * devtools — and no credential was sent at all.
 *
 * The two load-bearing rules here:
 *
 *   1. `stripClientScope` / `stripScopeFromBody` (lib/scope.ts) remove any
 *      `tenant_id` / `user_id` the client supplied, from both the query string and
 *      the JSON body, *before* the server's own values are inserted. A crafted
 *      request cannot smuggle a different tenant through.
 *   2. The upstream API base URL is server-only (`MEMORYOPS_API_URL`), so no
 *      long-lived API credential is ever exposed via `NEXT_PUBLIC_*`.
 */

export const dynamic = "force-dynamic";

const API_URL =
  process.env.MEMORYOPS_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Hop-by-hop and identity headers that must not be forwarded from the browser. */
const BLOCKED_REQUEST_HEADERS = new Set([
  "host",
  "connection",
  "content-length",
  "authorization",
  "cookie",
  "x-memoryops-tenant",
  "x-memoryops-user",
  // A browser must never supply its own role. The BFF sets this from the
  // server-resolved session below; anything inbound is stripped first.
  "x-memoryops-roles",
  "x-memoryops-actor-type",
]);

async function proxy(request: Request, path: string[]): Promise<Response> {
  const targetPath = `/${path.join("/")}`;
  const method = request.method;

  // ── who is calling ────────────────────────────────────────────────────────
  let identity;
  try {
    identity = await resolveIdentity();
  } catch (error) {
    if (error instanceof UnauthenticatedError) {
      return NextResponse.json({ detail: "not authenticated" }, { status: 401 });
    }
    throw error;
  }

  // ── may they do this ──────────────────────────────────────────────────────
  const needed = requiredRole(targetPath, method);
  if (!hasAtLeast(identity.role, needed)) {
    return NextResponse.json(
      { detail: "insufficient role", required_role: needed },
      { status: 403 },
    );
  }

  // ── build the upstream request with server-controlled scope ───────────────
  const incoming = new URL(request.url);
  const query = stripClientScope(new URLSearchParams(incoming.search));
  query.set("tenant_id", identity.tenantId);
  query.set("user_id", identity.userId);

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!BLOCKED_REQUEST_HEADERS.has(key.toLowerCase())) headers.set(key, value);
  });
  headers.set("content-type", "application/json");

  let credential;
  try {
    credential = await apiCredential(identity);
  } catch (error) {
    // Misconfiguration (e.g. auth_mode=jwt with no signing key) must fail closed
    // rather than silently calling the API with no credential.
    return NextResponse.json(
      { detail: (error as Error).message },
      { status: 500 },
    );
  }
  if (credential.kind === "jwt") {
    headers.set("authorization", `Bearer ${credential.token}`);
  } else if (credential.kind === "trusted_header") {
    headers.set("x-memoryops-tenant", identity.tenantId);
    headers.set("x-memoryops-user", identity.userId);
    // Without this the API sees no role claim at all, so an auditor session was
    // downgraded to the least-privileged default at the API boundary.
    headers.set("x-memoryops-roles", apiRoleForWebRole(identity.role));
  }

  let body: string | undefined;
  if (method !== "GET" && method !== "HEAD") {
    const raw = await request.text();
    if (raw) {
      try {
        body = JSON.stringify({
          ...(stripScopeFromBody(JSON.parse(raw)) as Record<string, unknown>),
          tenant_id: identity.tenantId,
          user_id: identity.userId,
        });
      } catch {
        return NextResponse.json({ detail: "invalid JSON body" }, { status: 400 });
      }
    } else {
      body = JSON.stringify({ tenant_id: identity.tenantId, user_id: identity.userId });
    }
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}${targetPath}?${query.toString()}`, {
      method,
      headers,
      body,
      cache: "no-store",
    });
  } catch {
    // Never surface the upstream URL or error text to the browser.
    return NextResponse.json({ detail: "upstream unavailable" }, { status: 502 });
  }

  const payload = await upstream.text();
  return new NextResponse(payload, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}

type Ctx = { params: { path: string[] } };

export async function GET(request: Request, { params }: Ctx) {
  return proxy(request, params.path);
}
export async function POST(request: Request, { params }: Ctx) {
  return proxy(request, params.path);
}
export async function PATCH(request: Request, { params }: Ctx) {
  return proxy(request, params.path);
}
export async function PUT(request: Request, { params }: Ctx) {
  return proxy(request, params.path);
}
export async function DELETE(request: Request, { params }: Ctx) {
  return proxy(request, params.path);
}
