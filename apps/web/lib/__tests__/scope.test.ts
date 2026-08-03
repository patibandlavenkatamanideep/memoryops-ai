import { describe, expect, it } from "vitest";

import { SCOPE_KEYS, stripClientScope, stripScopeFromBody } from "../scope";

/**
 * The BFF's security boundary: a client must not be able to choose its tenant.
 *
 * Before this existed, `lib/api.ts` put `tenant_id=tenant_demo&user_id=user_demo`
 * into the query string or body of every request straight from the browser. The
 * scope was client-controlled request data — trivially editable in devtools — and
 * no credential accompanied it.
 */

describe("stripClientScope (query string)", () => {
  it("removes client-supplied tenant and user", () => {
    const params = new URLSearchParams("tenant_id=victim&user_id=admin&status=active");
    stripClientScope(params);
    expect(params.get("tenant_id")).toBeNull();
    expect(params.get("user_id")).toBeNull();
  });

  it("preserves every non-scope parameter", () => {
    const params = new URLSearchParams("tenant_id=victim&status=active&memory_type=preference");
    stripClientScope(params);
    expect(params.get("status")).toBe("active");
    expect(params.get("memory_type")).toBe("preference");
  });

  it("removes repeated scope parameters, not just the first", () => {
    // URLSearchParams keeps duplicates; a single delete must clear them all or a
    // second value could survive and reach the API.
    const params = new URLSearchParams("tenant_id=a&tenant_id=b&tenant_id=c");
    stripClientScope(params);
    expect(params.getAll("tenant_id")).toEqual([]);
  });

  it("leaves the server free to set the authoritative scope afterwards", () => {
    const params = stripClientScope(new URLSearchParams("tenant_id=victim"));
    params.set("tenant_id", "real-tenant");
    expect(params.getAll("tenant_id")).toEqual(["real-tenant"]);
  });
});

describe("stripScopeFromBody", () => {
  it("removes tenant and user from a JSON body", () => {
    const cleaned = stripScopeFromBody({
      tenant_id: "victim",
      user_id: "admin",
      message: "hello",
    }) as Record<string, unknown>;
    expect(cleaned).toEqual({ message: "hello" });
  });

  it("does not mutate the caller's object", () => {
    const original = { tenant_id: "victim", message: "hi" };
    stripScopeFromBody(original);
    expect(original.tenant_id).toBe("victim");
  });

  it("passes through non-object bodies untouched", () => {
    expect(stripScopeFromBody(null)).toBeNull();
    expect(stripScopeFromBody("a string")).toBe("a string");
    expect(stripScopeFromBody([{ tenant_id: "x" }])).toEqual([{ tenant_id: "x" }]);
  });

  it("covers exactly the documented scope keys", () => {
    expect([...SCOPE_KEYS]).toEqual(["tenant_id", "user_id"]);
  });
});
