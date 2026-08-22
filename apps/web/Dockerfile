# MemoryOps AI — Web image (Next.js).
FROM node:20-slim AS deps
WORKDIR /app
# package-lock.json is required (not `package-lock.json*`): a missing lockfile must
# fail the build, not silently resolve fresh transitives at image-build time.
COPY package.json package-lock.json ./
# `npm ci` only — never `|| npm install`. The fallback defeated the lockfile: a stale
# or absent lock silently regenerated the tree, so the image could ship dependency
# versions no one reviewed and CI never saw.
RUN npm ci

# Production dependency tree, resolved from the same lockfile.
#
# This stage exists because the runtime image used to copy `node_modules` straight
# out of the build stage, and that tree is the output of a plain `npm ci` — every
# devDependency included. The shipped image therefore carried eslint, typescript,
# vitest, tailwind and the whole lint toolchain, none of which `next start` ever
# loads. They were not reachable, but they were present: extra bytes, extra CVE
# surface in image scans, and a runtime that did not match what it claimed to be.
#
# `npm ci --omit=dev` from the identical lockfile, rather than pruning the build
# tree, so the runtime dependency set is derived from the lock rather than from
# whatever `npm prune` decides is unreachable.
FROM node:20-slim AS prod-deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

FROM node:20-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-slim AS run
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
# Runtime dependencies only — note this comes from `prod-deps`, not `build`.
COPY --from=prod-deps /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
