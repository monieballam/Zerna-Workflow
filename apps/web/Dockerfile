# ============================================================
# Zerna Web App — Next.js 14
# Multi-stage build with pnpm workspaces
# ============================================================

# --------------- Stage 1: Install dependencies --------------
FROM node:20-alpine AS deps

ARG PNPM_VERSION=8.15.0

RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate

WORKDIR /build

# Copy workspace root files
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

# Copy package.json for workspace packages this app depends on
COPY apps/web/package.json apps/web/
COPY packages/sdk/package.json packages/sdk/

RUN pnpm install --frozen-lockfile

# --------------- Stage 2: Build the application -------------
FROM node:20-alpine AS builder

ARG PNPM_VERSION=8.15.0
ARG NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
ARG NEXT_PUBLIC_WS_URL=ws://127.0.0.1:8000

RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate

WORKDIR /build

COPY --from=deps /build/node_modules ./node_modules
COPY --from=deps /build/apps/web/node_modules ./apps/web/node_modules
COPY --from=deps /build/packages/sdk/node_modules ./packages/sdk/node_modules

# Copy source files
COPY packages/sdk/ packages/sdk/
COPY apps/web/ apps/web/
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

# Build Next.js with standalone output
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL}
RUN pnpm --filter @zerna/web build

# --------------- Stage 3: Production runtime ----------------
FROM node:20-alpine AS runtime

ARG NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
ARG NEXT_PUBLIC_WS_URL=ws://127.0.0.1:8000

RUN addgroup --system --gid 1001 zerna && \
    adduser --system --uid 1001 zerna

WORKDIR /app

# Copy standalone build output
COPY --from=builder /build/apps/web/.next/standalone ./
COPY --from=builder /build/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder /build/apps/web/public ./apps/web/public

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME="0.0.0.0" \
    PORT=3000 \
    NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL}

USER zerna

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1

CMD ["node", "apps/web/server.js"]
