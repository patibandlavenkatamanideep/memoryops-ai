/**
 * The proxy at runtime: a denied request must never reach the API.
 *
 * Source-level tests prove the check is present; this proves it *runs before* the
 * upstream call. A capability check placed after `fetch` would still return 403 to
 * the browser while the API had already done the work — and the API's own
 * enforcement would be the only thing that stopped it, which is exactly the
 * defence-in-depth claim this layer makes.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const identity = {
  tenantId: "acme",
  userId: "alice",
  role: "viewer" as string,
  isDemo: false,
};

vi.mock("@/lib/identity", () => ({
  resolveIdentity: vi.fn(async () => identity),
  UnauthenticatedError: class UnauthenticatedError extends Error {},
}));

vi.mock("@/lib/memoryopsToken", () => ({
  apiCredential: vi.fn(async () => ({ kind: "trusted_header" as const })),
}));

const { GET, POST, PATCH, DELETE } = await import("@/app/api/memoryops/[...path]/route");

type FetchArgs = [input: string, init?: RequestInit];

const fetchMock = vi.fn<(...args: FetchArgs) => Promise<Response>>(
  async () =>
    new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
);
vi.stubGlobal("fetch", fetchMock);

function ctx(path: string[]) {
  return { params: { path } };
}

function req(url: string, init?: RequestInit) {
  return new Request(url, init);
}

beforeEach(() => {
  fetchMock.mockClear();
  identity.role = "viewer";
});

describe("a denied request never reaches upstream", () => {
  it("refuses a mutation the persona cannot attempt", async () => {
    const response = await DELETE(
      req("http://web/api/memoryops/api/memories/abc", { method: "DELETE" }),
      ctx(["api", "memories", "abc"]),
    );
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses an unclassified path", async () => {
    identity.role = "owner";
    const response = await GET(
      req("http://web/api/memoryops/api/brand/new"),
      ctx(["api", "brand", "new"]),
    );
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses an unknown PATCH transition", async () => {
    identity.role = "owner";
    const response = await PATCH(
      req("http://web/api/memoryops/api/memories/abc", {
        method: "PATCH",
        body: JSON.stringify({ status: "deleted" }),
      }),
      ctx(["api", "memories", "abc"]),
    );
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a tenant persona a deployment surface", async () => {
    identity.role = "owner";
    const response = await GET(req("http://web/api/memoryops/api/traces"), ctx(["api", "traces"]));
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("describes the missing capability, not the persona's rank", async () => {
    identity.role = "memory_admin";
    const response = await GET(
      req("http://web/api/memoryops/api/evidence/policy"),
      ctx(["api", "evidence", "policy"]),
    );
    expect(response.status).toBe(403);
    const body = await response.json();
    expect(body.detail).toBe("insufficient capability");
    expect(body.required_permissions).toContain("evidence:read");
    expect(body).not.toHaveProperty("required_role");
    // No credential or claim material in a denial.
    expect(JSON.stringify(body)).not.toMatch(/authorization|bearer|token|x-memoryops/i);
  });
});

describe("an allowed request still has its scope replaced", () => {
  it("strips client-supplied tenant and user from the query", async () => {
    identity.role = "developer";
    await GET(
      req("http://web/api/memoryops/api/memories?tenant_id=evilcorp&user_id=mallory"),
      ctx(["api", "memories"]),
    );
    expect(fetchMock).toHaveBeenCalledOnce();
    const url = new URL(fetchMock.mock.calls[0][0]);
    expect(url.searchParams.get("tenant_id")).toBe("acme");
    expect(url.searchParams.get("user_id")).toBe("alice");
  });

  it("strips client-supplied scope from the body", async () => {
    identity.role = "developer";
    await POST(
      req("http://web/api/memoryops/api/chat", {
        method: "POST",
        body: JSON.stringify({ tenant_id: "evilcorp", user_id: "mallory", message: "hi" }),
      }),
      ctx(["api", "chat"]),
    );
    expect(fetchMock).toHaveBeenCalledOnce();
    const sent = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(sent.tenant_id).toBe("acme");
    expect(sent.user_id).toBe("alice");
    expect(sent.message).toBe("hi");
  });

  it("sends the mapped API role, not the web persona", async () => {
    identity.role = "auditor";
    await GET(
      req("http://web/api/memoryops/api/evidence/policy"),
      ctx(["api", "evidence", "policy"]),
    );
    expect(fetchMock).toHaveBeenCalledOnce();
    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("x-memoryops-roles")).toBe("auditor");
  });

  it("reads the body only once, so an allowed PATCH still forwards it", async () => {
    identity.role = "developer";
    const response = await PATCH(
      req("http://web/api/memoryops/api/memories/abc", {
        method: "PATCH",
        body: JSON.stringify({ content: "corrected" }),
      }),
      ctx(["api", "memories", "abc"]),
    );
    expect(response.status).toBe(200);
    const sent = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(sent.content).toBe("corrected");
  });
});
