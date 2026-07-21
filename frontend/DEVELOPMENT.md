# Npcink AI Cloud Frontend Development

This document describes the current repository truth for the Cloud frontend.
Treat it as an execution guide for local development, verification, and bounded
surface changes.

## Scope

The current frontend owns three bounded surface families:

1. `/(marketing)/*`
2. `/portal/*`
3. `/admin/*`

These surfaces share tokens and shell primitives, but they do not share the
same product voice:

- marketing: public product and onboarding surface
- portal: authenticated member workspace
- admin: operator / platform-admin surface

The frontend must not grow a second backend truth, a second session truth, or a
GA-style customer billing front-office narrative.

## Current Route Inventory

### Marketing

- `/`

### Portal

- `/portal`
- `/portal/login`
- `/portal/usage`
- `/portal/billing`
- `/portal/audit`

### Admin

- `/admin`
- `/admin/login`
- `/admin/accounts`
- `/admin/sites/[siteId]`
- `/admin/subscriptions`
- `/admin/plans`

### BFF / Auth / Health Handlers

- `src/app/api/portal/**`
- `src/app/api/admin/**`
- `src/app/admin/auth/**`
- `src/app/api/health/route.ts`
- `src/proxy.ts`

## Actual Tech Stack

- Next.js `16.2.x`
- React `19`
- TypeScript `5.9`
- Tailwind CSS `3.4`
- ESLint `8` + `eslint-config-next`
- Playwright for screenshot and smoke coverage
- Docker local development via the repository root `docker-compose.dev.yml`

Current dev compose runs the frontend with:

```bash
pnpm exec next dev --webpack -H 0.0.0.0
```

Do not describe this setup as Turbopack or Tailwind 4 unless the implementation
is actually migrated.

## Environment Layout

Local development uses:

- `.env`
- `.env.local`

`.env.local` is for local-only debug credentials and is gitignored.
Production-style remote deploys use:

- `.env.deploy`

Do not move local debug tokens into deploy env files.

## Local Development

Preferred entrypoint from the repository root:

```bash
pnpm run dev
```

The repository root owns the only dependency lock. `frontend/pnpm-lock.yaml`
must not exist. Bootstrap pnpm through the root `packageManager` declaration and
install the frontend workspace from the repository root:

```bash
corepack enable
corepack install
pnpm install --frozen-lockfile --filter frontend...
```

Local Docker and CI use the same root lock and frozen workspace install. When
`frontend/package.json` changes, refresh only the root `pnpm-lock.yaml` from
the repository root.

Local development URL:

- `http://127.0.0.1:8010`

If you need a non-default mini-dev hostname or tunnel endpoint, set
`NPCINK_CLOUD_FRONTEND_DEV_HOST_ALLOWLIST=host1,host2` before starting the
frontend. The default allowlist only includes `127.0.0.1`, `localhost`, and
`0.0.0.0`.

Compose roles:

- `frontend`: Next.js dev server
- `proxy`: unified development entry on `8010`
- `api`: portal/admin backend seam
- `worker`: async runtime queue worker
- `postgres` / `redis`: local state services

## Frontend Verification

Run from the repository root:

```bash
pnpm run frontend:type-check
pnpm run frontend:lint
pnpm run check:visual:frontend
```

Additional Cloud seam checks when the task touches auth, env, proxy, or BFF:

```bash
pnpm run test:api
pnpm run check:perimeter
```

## i18n Rules

- Supported locales are `en`, `zh-CN`, and `zh-TW`
- New visible copy must be added to `src/lib/i18n.ts`
- Do not rely on fallback English for shipped or local-debug visible UI copy

Minimum manual locale checks:

- `http://127.0.0.1:8010/`
- `http://127.0.0.1:8010/portal/login`
- `http://127.0.0.1:8010/admin/login?lang=zh-CN`
- `http://127.0.0.1:8010/admin/login?lang=zh-TW`

## Change Boundaries

Pure UI tasks usually stay inside:

- `src/app/**`
- `src/components/**`
- `src/contexts/**`
- `src/hooks/**`

Escalate carefully when touching:

- `src/app/api/**`
- `src/lib/**`
- `src/proxy.ts`
- env or deploy wiring

Those files are not forbidden, but they are no longer UI-only changes and must
be validated against Cloud seams, not just visual output.
