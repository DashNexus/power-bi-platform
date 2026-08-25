# syntax=docker/dockerfile:1
#
# Three stages so the runtime image carries neither the build toolchain nor the
# dev dependencies: deps installs, builder compiles, runner ships.

FROM node:22-alpine AS deps
WORKDIR /app
# npm ci needs both files and installs exactly the lockfile — a resolution that
# drifts between build and deploy is the failure this avoids.
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* is inlined at build time, not read at runtime: the browser bundle
# is static by then. The API URL therefore has to be supplied here, and an image
# built for one environment cannot be promoted to another without a rebuild.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 10001 nodejs \
    && adduser --system --uid 10001 nextjs

# `output: 'standalone'` (next.config.ts) produces server.js plus a pruned
# node_modules. static/ and public/ are not included in it and are copied
# separately — omitting either serves a page with no CSS.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000/login',r=>process.exit(r.statusCode<500?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "server.js"]
