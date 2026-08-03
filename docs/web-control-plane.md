# Web control plane (apps/web)

The Next.js app runs in one of two explicit modes. Identity is resolved **only on
the server** and is never accepted from the browser.

```
MEMORYOPS_WEB_MODE=demo            # shared tenant_demo, no auth, visible banner
MEMORYOPS_WEB_MODE=authenticated   # Auth.js session -> tenant/user/role
```

## The problem this replaces

`lib/api.ts` used to export hardcoded constants:

```ts
export const DEMO_TENANT = "tenant_demo";
export const DEMO_USER = "user_demo";
```

and attach them to every request **from the browser** — in the query string or the
JSON body. Three consequences:

1. There was no identity at all: every visitor was the same tenant and user.
2. The scope travelled as client-controlled request data, so it was editable in
   devtools. The API's scope validation is what stopped cross-tenant access, but
   only when `MEMORYOPS_AUTH_MODE` is set.
3. The app sent **no credential**, so it could only work against
   `MEMORYOPS_AUTH_MODE=none` — which `MEMORYOPS_PROFILE=production` refuses to
   run. The official UI and the production security profile were mutually
   exclusive: you could have one or the other, never both.

## Architecture

```
Browser ──(same-origin session cookie)──▶ Next.js BFF route handler
                                            /api/memoryops/[...path]
                                                    │
                                    resolveIdentity()  ← server-only
                                    strip client tenant_id/user_id
                                    insert server tenant_id/user_id
                                    mint short-lived HS256 JWT
                                                    ▼
                                          MemoryOps API (auth_mode=jwt)
```

| Module | Responsibility |
| --- | --- |
| `lib/identity.ts` | `server-only`. Resolves mode + identity. Never falls back to demo in authenticated mode — a broken session fails closed. |
| `lib/roles.ts` | Pure role model + path→role policy. No `server-only`/NextAuth imports, so it is directly unit-testable. |
| `lib/scope.ts` | Strips client-supplied `tenant_id`/`user_id` from query and body. The security boundary. |
| `lib/memoryopsToken.ts` | Mints the short-lived API credential. Never reaches the browser. |
| `app/api/memoryops/[...path]/route.ts` | The BFF proxy. The browser's only route to the API. |
| `auth.ts` | Auth.js v5 config; the `jwt` callback maps provider claims → `tenantId`/`memoryopsUserId`/`role`. |
| `middleware.ts` | Redirects unauthenticated humans to `/signin`. **Not** the security boundary. |

### Why the browser cannot switch tenant

`stripClientScope` / `stripScopeFromBody` delete `tenant_id` and `user_id` from
both the query string and the JSON body *before* the server's own values are
inserted. A crafted request cannot smuggle a different tenant through. This is
covered by `lib/__tests__/scope.test.ts`, including the repeated-parameter case
(`?tenant_id=a&tenant_id=b`) where deleting only the first value would let the
second survive.

`MEMORYOPS_WEB_MODE` is deliberately **not** `NEXT_PUBLIC_*`: authorization must
never be decided by a value the browser bundle can read. `NEXT_PUBLIC_MEMORYOPS_WEB_MODE`
exists for the banner only and is never consulted for access decisions.

The upstream API base is `MEMORYOPS_API_URL` (server-only), so no API credential is
exposed through `NEXT_PUBLIC_*`.

## Roles

Least privilege first: `viewer` → `developer` → `auditor` → `memory_admin` → `owner`.

| API path | GET | Write |
| --- | --- | --- |
| `/api/memories` | `viewer` | `memory_admin` |
| `/api/chat` | — | `developer` (chat writes memory) |
| `/api/audit`, `/api/evidence` | `auditor` | `auditor` |
| `/api/retention` | `auditor` | `owner` |
| `/api/evals` | `owner` | `owner` |
| anything else | `viewer` | `viewer` |

Unknown paths default to the **least** privileged role, so a newly added endpoint
is readable rather than accidentally open to mutation. This is defence in depth on
top of the API's governance — it only ever *removes* access.

## Identity provider

`auth.ts` ships a Credentials provider reading `MEMORYOPS_WEB_OPERATORS`
(`tenant:user:role:password`, comma-separated) so the authenticated flow is runnable
and testable offline with no external IdP. **It is a seam, not a recommendation** —
replace it with your real provider:

```ts
providers: [GitHub],   // or Okta, Auth0, Entra, ...
```

Nothing downstream changes: the `jwt` callback is the single place provider claims
are mapped onto `tenantId` / `memoryopsUserId` / `role`, and every other module
reads only those three fields. MemoryOps stays identity-neutral (see
[auth-adapters.md](auth-adapters.md)).

## Configuration

```bash
# demo (default)
MEMORYOPS_WEB_MODE=demo

# authenticated
MEMORYOPS_WEB_MODE=authenticated
AUTH_SECRET=$(openssl rand -base64 32)
MEMORYOPS_WEB_OPERATORS=acme:alice:owner:<password>
MEMORYOPS_API_URL=https://api.internal          # server-only
MEMORYOPS_AUTH_MODE=jwt                          # must match the API
MEMORYOPS_AUTH_JWT_KEY=<same key as the API>
MEMORYOPS_API_TOKEN_TTL_SECONDS=120
```

`AUTH_SECRET` is a **runtime** signing key. The build does not need it, and no
placeholder is baked into the image.

## Known limitations

- `next-auth@5.0.0-beta.32` is a **beta** release. It is the App-Router-native
  option and is widely deployed, but it is pinned exactly and should be re-pinned
  deliberately when v5 goes stable.
- The Credentials provider compares passwords from an env var. It exists to make
  the flow testable offline; use a real IdP for anything beyond that.
- `middleware.ts` only checks for the *presence* of a session cookie. A forged
  cookie passes the redirect and is then rejected with 401 by the BFF, which
  re-resolves identity server-side on every call. Do not rely on middleware for
  authorization.
- Organisation/project/service-account management, and first-class consent /
  legal-hold / retention / evidence pages, are not built yet — the API and SDK
  expose them but the UI does not.
- `next@14.2.35` currently carries open advisories (see `npm audit`); fixing them
  requires a Next 16 upgrade, tracked separately from this change.
