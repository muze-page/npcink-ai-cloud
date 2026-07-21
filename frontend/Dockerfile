FROM node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS base

RUN apk add --no-cache \
    gcompat=1.1.0-r4 \
    libucontext=1.5.1-r0 \
    musl-obstack=1.2.3-r2

FROM base AS deps

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend/package.json ./frontend/package.json

RUN corepack enable && \
    corepack prepare "$(node -p "require('./package.json').packageManager")" --activate && \
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

RUN set -eux; \
    apk add --no-cache dumb-init=1.2.5-r4; \
    test "$(command -v node)" = /usr/local/bin/node; \
    test ! -L /usr/local/bin/node; \
    test "$(command -v npm)" = /usr/local/bin/npm; \
    test "$(command -v npx)" = /usr/local/bin/npx; \
    test "$(command -v corepack)" = /usr/local/bin/corepack; \
    test "$(command -v yarn)" = /usr/local/bin/yarn; \
    test "$(command -v yarnpkg)" = /usr/local/bin/yarnpkg; \
    test "$(readlink -f /usr/local/bin/npm)" = /usr/local/lib/node_modules/npm/bin/npm-cli.js; \
    test "$(readlink -f /usr/local/bin/npx)" = /usr/local/lib/node_modules/npm/bin/npx-cli.js; \
    test "$(readlink -f /usr/local/bin/corepack)" = /usr/local/lib/node_modules/corepack/dist/corepack.js; \
    test "$(readlink -f /usr/local/bin/yarn)" = /opt/yarn-v1.22.22/bin/yarn; \
    test "$(readlink -f /usr/local/bin/yarnpkg)" = /opt/yarn-v1.22.22/bin/yarnpkg; \
    test "$(find /usr/local/lib/node_modules -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort)" = "$(printf 'corepack\nnpm')"; \
    test "$(find /opt -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort)" = yarn-v1.22.22; \
    rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
        /usr/local/bin/yarn /usr/local/bin/yarnpkg; \
    rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack; \
    rm -rf /opt/yarn-v1.22.22; \
    rmdir /usr/local/lib/node_modules; \
    rmdir /opt; \
    test -x /usr/local/bin/node; \
    node -e "if (typeof fetch !== 'function') process.exit(1)"; \
    test -z "$(command -v npm || true)"; \
    test -z "$(command -v npx || true)"; \
    test -z "$(command -v corepack || true)"; \
    test -z "$(command -v yarn || true)"; \
    test -z "$(command -v yarnpkg || true)"; \
    test ! -e /usr/local/lib/node_modules; \
    test ! -e /opt

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
    CMD test "$(command -v node)" = /usr/local/bin/node && \
        test ! -e /usr/local/lib/node_modules && \
        test -z "$(command -v npm || true)" && \
        test -z "$(command -v npx || true)" && \
        test -z "$(command -v corepack || true)" && \
        test -z "$(command -v yarn || true)" && \
        test -z "$(command -v yarnpkg || true)" && \
        test ! -e /opt && \
        node -e "fetch('http://127.0.0.1:3000/api/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

ENTRYPOINT ["dumb-init", "--", "/bin/sh", "-eu", "-c", "test \"$(command -v node)\" = /usr/local/bin/node; test ! -e /usr/local/lib/node_modules; test ! -e /opt; test -z \"$(command -v npm || true)\"; test -z \"$(command -v npx || true)\"; test -z \"$(command -v corepack || true)\"; test -z \"$(command -v yarn || true)\"; test -z \"$(command -v yarnpkg || true)\"; exec \"$@\"", "cloud-frontend-runtime"]
CMD ["node", "frontend/server.js"]
