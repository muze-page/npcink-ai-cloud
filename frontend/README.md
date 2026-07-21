# Npcink AI Cloud Frontend

Next.js App Router frontend for the bounded Cloud web surfaces. The shipped
frontend has three clearly separated surface families:

- `/(marketing)/*`: public product and onboarding surface
- `/portal/*`: authenticated user workspace for users
- `/admin/*`: internal platform-admin console

This frontend is not a separate backend truth and it is not a second control
plane. Local WordPress remains the control-plane truth for runtime mode,
router truth, prompt/preset truth, and final WordPress writes.

Commercial copy freeze for frontend surfaces:

- points are presentation, not a ledger
- operator top-up is current billing period only
- no wallet
- no permanent credit

## Surface Responsibilities

### Cloud Admin Console

- Entry for: `platform_admin`
- Home: `/admin/*`
- Purpose: internal platform operations only
- Current commercial scope is bounded to operator/admin guidance:
  - `/admin/plans`
  - `/admin/subscriptions`
  - no customer storefront, wallet, checkout, invoice, or self-serve buy flow
- Top-level navigation is intentionally grouped into:
  - `Overview`
  - `Commercial Ops`
  - `Model Ops`
  - `Support / Access`


### Cloud Portal

- Entry for: `user`
- Home: `/portal/*`
- Purpose: user workspace, not a smaller admin console
- Portal may expose bounded billing/usage detail, but it must not be described
  or implemented as a commercial front-office.
- Top-level navigation is intentionally limited to:
  - `Workspace`
  - `API Keys`
  - `Usage`
  - `Billing`
  - `Audit`
  - `Settings`


### Cloud Addon Boundary

- The WordPress Cloud addon is only an access shell.
- It is not a third admin console.
- It may link into `/portal/*` and `/admin/*`, but it does not own platform
  operations or user workspace detail.

## Current Surface Inventory

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
- grouped under:
  - `Overview`
  - `Commercial Ops`
    - `/admin/plans`
    - `/admin/subscriptions`
    - `/admin/accounts`
    - `/admin/sites/[siteId]`

### BFF / Route Handlers

- `src/app/api/portal/**`
- `src/app/api/admin/**`
- `src/app/admin/auth/**`
- `src/app/api/health/route.ts`

## Tech Stack

- Next.js `16.2.x`
- React `19`
- TypeScript `5.9`
- Tailwind CSS `3.4`
- ESLint `8` with `eslint-config-next`
- Playwright for visual and route-level frontend checks

## Real Development Flow

### Preferred local dev

From the repository root:

```bash
pnpm run dev
```

The root `pnpm-lock.yaml` is the only dependency lock. Do not create a
`frontend/pnpm-lock.yaml`. Corepack reads the pinned pnpm version from the root
`packageManager` field, and dependency installs run from the repository root:

```bash
corepack enable
corepack install
pnpm install --frozen-lockfile --filter frontend...
```

Unified local dev entry:

- `http://127.0.0.1:8010`

The dev stack is served through `docker-compose.dev.yml`:

- `frontend` runs `next dev --webpack`
- `proxy` exposes the unified local dev entry on port `8010`
- `api` and `worker` provide the portal/admin backing seams

### Frontend-only commands

From `frontend/`:

```bash
pnpm dev
pnpm build
pnpm start
pnpm type-check
pnpm lint
pnpm test:visual
```

For build-backed Playwright E2E runs, set non-loopback origins so production
env guards do not reject the build:

```bash
CLOUD_API_BASE_URL=https://api.example.com
CLOUD_PUBLIC_BASE_URL=https://cloud.example.com
```

### Playwright browsers

Cloud frontend Playwright runs use one shared browser cache path by default:

- `PLAYWRIGHT_BROWSERS_PATH=~/.local/share/magick-ai-playwright`

This matches the project runner in
[`scripts/run-cloud-frontend-playwright.js`](../scripts/run-cloud-frontend-playwright.js)
and avoids re-downloading Chromium into ad-hoc cache locations.

From `frontend/`:

```bash
pnpm run playwright:browsers:check
pnpm run playwright:browsers:install:chromium
pnpm run playwright:browsers:prune:check
```

If you need a custom browser cache location, override
`PLAYWRIGHT_BROWSERS_PATH` explicitly before running the install or E2E
commands.

Recommended admin operator E2E entrypoint:

```bash
pnpm run test:e2e:admin-operator-path:ci
```

That script wires the standard browser cache path plus safe placeholder
`CLOUD_API_BASE_URL` / `CLOUD_PUBLIC_BASE_URL` defaults for build-backed runs.

Browser cache hygiene:

- `pnpm run playwright:browsers:prune:check`
  - show stale Chromium / headless-shell directories that are no longer the
    newest cached revisions
- `pnpm run playwright:browsers:prune`
  - remove only those stale browser directories from the shared cache path

## Verification

From the repository root:

```bash
pnpm run frontend:type-check
pnpm run frontend:lint
pnpm run check:visual:frontend
```

When a task touches auth, admin, portal BFF, env, or proxy seams, keep using the
Cloud verification ladder from the repo root instead of treating it as a pure UI
task.

## Role Split

Use this split consistently in code, copy, and navigation:

- `/admin/*`
  - platform administrator only
  - internal operations console
  - never reuse portal user wording here
- `/portal/*`
  - user only
  - current site workspace
  - never mirror admin object inventory here
- addon
  - WordPress entry shell only
  - links out to Cloud surfaces when deeper detail is needed

Do not reintroduce old flat admin navigation or legacy portal wording that makes
portal look like a reduced operator console.

## Local Env Notes

Keep local-only debug credentials in:

- `.env.local`

That file is gitignored and used by local dev compose. Production-style remote
deploys use:

- `.env.deploy`

Do not copy local debug tokens into deploy env files.
