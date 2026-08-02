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
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
