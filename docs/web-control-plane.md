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
| `lib/webRoles.ts`, `lib/capabilities.ts` | The persona list and the generated capability contract. No `server-only`/NextAuth imports, so both are directly unit-testable. |
| `lib/scope.ts` | Strips client-supplied `tenant_id`/`user_id` from query and body. The security boundary. |
| `lib/memoryopsToken.ts` | Mints the short-lived API credential. Never reaches the browser. |
| `app/api/memoryops/[...path]/route.ts` | The BFF proxy. The browser's only route to the API. |
| `auth.ts` | Auth.js v5 config; the `jwt` callback maps provider claims → `tenantId`/`memoryopsUserId`/`role`. |
| `middleware.ts` | Redirects unauthenticated humans to `/signin`. **Not** the security boundary. See [Route protection](#route-protection). |

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

## Route protection

In `MEMORYOPS_WEB_MODE=authenticated`, `middleware.ts` decides which surfaces an
anonymous visitor may reach. In demo mode it is a no-op — the public demo has no
sign-in to redirect to.

| Route | Anonymous | Why |
| --- | --- | --- |
| `/` | **public** (v2.6) | Product landing surface. Static; makes no authenticated API call. |
| `/architecture` | public | Public reference, and the Railway web healthcheck (`railway/web.railway.json`). |
| `/signin` | public | The sign-in flow itself. |
| `/api/auth/*` | public | Auth.js callback, CSRF and session endpoints. |
| `/chat` | protected | |
| `/memories`, `/memories/{id}` | protected | |
| `/governance` | protected | |
| `/audit` | protected | |
| `/loops` | protected | |
| `/admin` | protected | |
| `/api/memoryops/*` | protected | The BFF proxy. Also refuses independently — a forged cookie gets a 401 here. |

### `/` is matched exactly, and must stay that way

Public paths were previously all tested with `pathname.startsWith(p)`. Under that
rule the single character `/` is a prefix of every route in the application, so
adding `/` to the list would have made the entire control plane anonymous in one
line — without naming `/chat`, `/memories`, `/governance`, `/audit`, `/loops` or
`/admin` anywhere in the diff.

`middleware.ts` therefore keeps two lists: `PUBLIC_EXACT` (matched with `===`,
holding `/`) and `PUBLIC_PREFIXES` (matched as the path itself or a `/`-delimited
descendant, so `/architecture-internal` is not covered by `/architecture`). Paths
containing a dot segment — literal or percent-encoded — are refused public status
outright: `new URL()` resolves `..` before `nextUrl.pathname` is read but does not
decode `%2e%2e`, so `/architecture/%2e%2e/chat` would otherwise satisfy a prefix
test while routing elsewhere.

`__tests__/middleware-route-protection.test.ts` asserts the matrix route by route
rather than re-deriving the rule, including `/memories/{id}`, the `__Secure-`
cookie name, demo mode, an unset mode, and the `config.matcher` exclusion list.
Reverting to the naive one-list implementation fails 12 of those tests.

### The public landing page must stay session-independent

A page that is publicly reachable but session-dependent does not fail politely:
`resolveIdentity()` throws in authenticated mode and the BFF returns 401, so the
new public surface would render as an error for exactly the visitors it was opened
for — and only in production, since demo mode resolves an identity for everyone.

`__tests__/public-landing-independence.test.ts` walks the whole first-party import
graph from `app/page.tsx` and `app/architecture/page.tsx` and fails if any module
in it reaches `lib/api`, `lib/identity` or `auth`. The realistic regression is not
a deliberate import — it is a later stage adding a live-metrics widget several
components deep.

Middleware remains a redirect for humans, not the boundary. Authorization is the
BFF's `canAttempt()` check plus the API's own re-decision after it loads the
record.

## Roles

**Web roles are UI personas. API roles are authorization bundles.** They are
different vocabularies, and the translation between them is explicit,
single-sourced in `contracts/auth-role-map.json`, and tested from both sides.

| Web persona | API role |
| --- | --- |
| `viewer` | `memory_viewer` |
| `developer` | `memory_user` |
| `auditor` | `auditor` |
| `memory_admin` | `memory_admin` |
| `owner` | `tenant_admin` |

Two API roles exist that no web persona maps to. `service_worker` is a machine
identity for the worker fleet and is never assignable to a human at all.
`platform_operator` *is* assignable to a person — it runs the deployment — but is
**never web-assignable**: no customer's UI session may become deployment
authority. Both are listed in `NEVER_WEB_ASSIGNABLE`, and `apiRoleFor()` returns
`null` for either.

### Personas are a list, not a ladder

There is no ordinal ranking. Authority is **capability-based**: each API role
holds a set of permissions, and those sets are not nested. Two concrete cases from
the generated contract disprove any ordering:

- `memory_admin` holds no `evidence:read`; `auditor` does. Managing memory does not
  confer access to the evidence of who managed it.
- `tenant_admin` (the `owner` persona) holds no `ops:*` permission of any kind;
  only `platform_operator` does. The highest tenant role reaches no deployment
  surface.

Do not reintroduce prose implying that `memory_admin` outranks `auditor`, or that
`owner` outranks everything. A ladder cannot express orthogonal capabilities, and
the previous `hasAtLeast()` model let both of those mistakes through.

### How a request is decided

```
web persona
  → explicit persona → API-role mapping        (contracts/auth-role-map.json)
  → generated authorization contract           (lib/authzCapabilities.generated.ts)
  → route + HTTP method + action-shape check   (lib/capabilities.ts, canAttempt)
  → BFF proxy decision                         (app/api/memoryops/[...path])
  → API authoritative, record- and state-aware authorization
```

`lib/authzCapabilities.generated.ts` is generated from the API's own
`authz_spec` and `roles` modules, so the web cannot drift from what the server
enforces. A CI gate (`python scripts/generate_web_capabilities.py --check`)
fails if it does.

`canAttempt()` answers exactly one question:

> May this persona attempt this request shape?

It does **not** answer:

> Is this operation authorized on this actual record?

The browser does not know a memory's stored owner, whether a request resolves to
self or tenant scope, the record's current lifecycle status, or anything about
legal hold, consent or revisions. `status: "active"` is genuinely ambiguous from
the client — it is *approve* from `pending` and *restore* from `archived` — so
both readings are permitted to be attempted and the API resolves the real
transition. **The API remains authoritative.** The BFF check only ever *removes*
access; it never grants any.

### Fail closed

Every unrecognised shape is denied, not defaulted:

| Situation | Result |
| --- | --- |
| Unknown or non-web-assignable persona | DENY |
| Route with no authorization contract | DENY |
| Unknown HTTP method for a known route | DENY |
| Unrecognised field in a `PATCH` body | DENY |
| Unrecognised lifecycle transition | DENY |
| Body that requests no change at all | DENY |
| Route classified but naming no permission | DENY |

A newly added API endpoint is therefore **unreachable through the BFF until it is
classified** — it is not readable by default. The earlier model fell through to the
least-privileged role, which meant an unclassified endpoint was readable by
everyone; that is the specific bug this replaced.

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

## Runtime dependencies

The web runtime is **Next.js 16.3.1** on React 18.3.1, with `next-auth`
5.0.0-beta.32. The production dependency tree audits clean.

### Why 16.3.1 specifically

This is worth stating precisely, because the short version is wrong.

The known **Next.js advisories themselves cleared earlier** — every one of them is
fixed by 15.5.21. What forced the move to 16 was a transitive dependency: `next`
pins `postcss` *exactly*, and the tested 15.x releases (15.5.21, 15.5.22, 15.5.23)
and 16.0.0 all still bundle the vulnerable `postcss@8.4.31`. Because the pin is
exact, no patched postcss could be hoisted underneath them.

`next@16.3.1` is the first release that ships the patched `postcss@8.5.23`. On
16.3.1 the nested `node_modules/next/node_modules/postcss` resolution disappears
entirely and the tree dedupes to the patched top-level copy.

So: **16.3.1 was selected to obtain a clean production dependency tree, not
because the Next.js advisories required Next 16.** Do not restate it the short way.

### Production tree vs development tree

These are different questions and should not be collapsed:

| Scope | Result |
| --- | --- |
| Production dependency tree (`npm audit --omit=dev`) | **clean** |
| Full development tree (`npm audit`) | findings remain in the ESLint/glob chain |
| Packages present in the production image | dev tooling excluded by the `prod-deps` stage |

See [Known limitations](#known-limitations) for why the development-tooling chain
is deferred rather than fixed.

### The build compiler is pinned

Next 16 defaults to Turbopack. The `build` and `dev` scripts pass `--webpack`
explicitly, so the compiler did not change when the framework did. Builds report
`▲ Next.js 16.3.1 (webpack)`. Adopting Turbopack is a separate, deliberate
decision rather than a side effect of a dependency upgrade.

`next lint` was removed in Next 16, so linting invokes ESLint directly
(`eslint . --ext .ts,.tsx,.js,.jsx`) against the existing ESLint 8 configuration.
That is a command-compatibility change only — no ESLint upgrade and no flat config.

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
- **Development-tooling advisories remain in the lockfile.** The production
  dependency tree audits clean, but `eslint-config-next` →
  `@next/eslint-plugin-next` → `glob` still carries findings. The vulnerable code
  is the glob **CLI** (`-c/--cmd`), which lint tooling never invokes, and the
  production image excludes these packages entirely via the `prod-deps` stage —
  but **not shipped is not the same as remediated**. Remediating it requires
  `eslint-config-next@16.3.1`, whose ESLint peer is `>=9.0.0`, i.e. an ESLint 9
  flat-config migration. That is deliberately deferred and tracked separately.
  Do not describe the repository's whole dependency graph as clean.
