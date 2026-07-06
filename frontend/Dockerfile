FROM node:20-alpine AS base

RUN apk add --no-cache libc6-compat

FROM base AS deps

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend/package.json ./frontend/package.json

RUN corepack enable && \
    corepack prepare pnpm@10.33.0 --activate && \
    pnpm install --frozen-lockfile --filter frontend...

FROM base AS builder

WORKDIR /app

COPY --from=deps /app ./
COPY frontend ./frontend

RUN mkdir -p frontend/public

ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
ARG CLOUD_API_BASE_URL=https://cloud.npc.ink
ARG CLOUD_PUBLIC_BASE_URL=https://cloud.npc.ink
ENV CLOUD_API_BASE_URL=${CLOUD_API_BASE_URL}
ENV CLOUD_PUBLIC_BASE_URL=${CLOUD_PUBLIC_BASE_URL}

RUN cd frontend && ./node_modules/.bin/next build

FROM base AS runner

RUN apk add --no-cache curl dumb-init

WORKDIR /app

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder /app/frontend/.next/standalone ./
COPY --from=builder /app/frontend/public ./frontend/public
COPY --from=builder /app/frontend/.next/static ./frontend/.next/static

RUN chown -R nextjs:nodejs /app

USER nextjs

EXPOSE 3000

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:3000/api/health || exit 1

ENTRYPOINT ["dumb-init", "--"]
CMD ["node", "frontend/server.js"]
