// The `server-only` package throws on import outside a React Server Component, so a
// plain node test cannot load a module that imports it. Aliased to this no-op in
// vitest.config.mts.
//
// This does not weaken the guarantee: `server-only` is a *build-time* guard that
// makes Next.js fail if a server module is pulled into a client bundle. The tests
// here exercise those modules in the environment they actually run in — the server.
export {};
