# syntax=docker/dockerfile:1.7
# Multi-stage build for the Next.js frontend. Uses Next's `output: "standalone"`
# so the runtime image only carries a trimmed server.js + node_modules.

FROM oven/bun:1.3-slim AS deps
WORKDIR /app
COPY apps/web/package.json apps/web/bun.lock ./
RUN bun install --frozen-lockfile

FROM oven/bun:1.3-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/package.json apps/web/bun.lock apps/web/tsconfig.json apps/web/next.config.mjs apps/web/next-env.d.ts ./
COPY apps/web/src ./src
RUN bun run build

FROM node:20-bookworm-slim AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 nextjs \
    && useradd --system --uid 1001 --gid 1001 --shell /bin/bash nextjs

# .next/standalone holds the minimal server. Static assets and the public/
# bundle live separately.
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:3000/api/health || exit 1

CMD ["node", "server.js"]
