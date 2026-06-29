# Npcink Cloud Local Docker Closeout - 2026-06-24

Status: local development closeout record.

This document summarizes the local Docker, portal/admin entry, and active
documentation cleanup completed after the Cloud repository moved from the old
Magick AI naming context to the standalone `npcink-ai-cloud` workspace.

## Initial Symptom

The local MINI dock showed two entries:

- `用户后台`
- `平台后台`

`平台后台` was usable, but `用户后台` could not enter the portal workspace.
The failure was reproduced from the local unified entry:

```bash
curl -i 'http://127.0.0.1:8010/portal/dev-entry?redirect=%2Fportal'
```

At first, the response redirected to:

```text
/portal/login?error=auth.origin_forbidden
```

After the origin issue was fixed, the next failure was:

```text
/portal/login?error=auth.dev_portal_code_unavailable
```

That second error was expected for an empty local database before any portal
site administrator was bound.

## Root Causes

### Old Docker Project Was Still Running

The active containers were still named with the retired compose project:

```text
magick-ai-cloud-*
```

The current repository and compose configuration expected:

```text
npcink-ai-cloud-*
```

This caused local state to split across old and new Docker resources.

### Old Database Volume Did Not Match Current Defaults

The old Postgres container had been initialized with Magick-era values:

```text
POSTGRES_DB=magick_ai_cloud
POSTGRES_USER=magick
```

The current Cloud API default expects:

```text
postgresql+psycopg://npcink:npcink@postgres:5432/npcink_ai_cloud
```

The API log showed Postgres authentication failures when it tried to use the
current Npcink defaults against the old initialized database state.

### Browser Origin Was Not Trusted For Local Portal Login

Portal login code request uses same-origin protection before issuing a code.
The local `portal/dev-entry` helper sends the debug header, but the backend
still needs local development origin configuration.

The missing local setting was:

```text
NPCINK_CLOUD_DEBUG_LOCAL_ORIGIN_ALLOWLIST=http://127.0.0.1:8010,http://localhost:8010
```

Portal public URL is now stored in `/admin/service-settings`, not `.env`.

### Portal User Was Not Bound In The Fresh Database

After moving to a clean Npcink database, `portal-demo@example.com` had no site
administrator grant. Portal dev-entry could request the login endpoint, but it
could not receive a development code until a real site and portal admin binding
existed.

## Completed Actions

### Backed Up The Old Database

Before stopping the old project, the old Magick-era database was dumped to:

```text
/Users/muze/gitee/npcink-ai-cloud-docker-backups/magick-ai-cloud-before-rename-20260624-023224.sql
```

The backup was moved outside the repository so it does not pollute Git status.

### Stopped The Old Compose Project

The old project was stopped and old containers/network were removed:

```bash
docker compose -p magick-ai-cloud -f docker-compose.dev.yml down --remove-orphans
docker rm -f $(docker ps -aq --filter label=com.docker.compose.project=magick-ai-cloud)
docker network rm magick-ai-cloud_default
```

Old volumes were intentionally preserved:

```text
magick-ai-cloud_cloud-postgres-dev
magick-ai-cloud_cloud-redis-dev
```

### Started The New Compose Project

The current project was rebuilt and started with the canonical project name:

```bash
COMPOSE_PROJECT_NAME=npcink-ai-cloud docker compose -f docker-compose.dev.yml up -d --build
```

Current running containers use:

```text
npcink-ai-cloud-*
```

### Migrated The New Database

The new Npcink database was migrated to the current Alembic head:

```bash
docker exec npcink-ai-cloud-api-1 alembic upgrade head
```

### Seeded And Bound The Local Portal Workspace

The local smoke site was seeded:

```bash
COMPOSE_PROJECT_NAME=npcink-ai-cloud pnpm run seed:smoke
```

The portal demo user was bound to `site_smoke`:

```bash
COMPOSE_PROJECT_NAME=npcink-ai-cloud \
  docker compose -f docker-compose.dev.yml run --rm api \
  python -m app.dev.bootstrap_portal_site \
  --site-id site_smoke \
  --site-admin-email portal-demo@example.com \
  --public-base-url http://127.0.0.1:8010
```

The binding result uses:

```text
site_id=site_smoke
account_id=acct_site_smoke
site_admin_ref=site_admin:portal-demo@example.com
```

## Script And Documentation Cleanup

The local portal bind wrapper was fixed:

- `dev/bootstrap-portal-site-dev.sh` now runs from the repository root.
- It uses `docker-compose.dev.yml` directly instead of `cloud/docker-compose.dev.yml`.
- It defaults `COMPOSE_PROJECT_NAME` to `npcink-ai-cloud`.
- It accepts README-style `--member-email` and maps it to the Python entry's
  `--site-admin-email`.

The active development and operations documents were updated to standalone
repository paths and current script names:

- `frontend/README.md`
- `frontend/DEVELOPMENT.md`
- `deploy/OPS_PLAYBOOK.md`
- `deploy/WORKSPACE_TARGET.md`
- `deploy/workspace-target.env.sh`
- `deploy/RELEASE_CHECKLIST.md`
- `README.md`

Active docs now use current commands such as:

```bash
pnpm run dev
pnpm run test:api
pnpm run check:perimeter
pnpm run check:e2e:deploy-bundle:smoke
pnpm run deploy:ssh
pnpm run env:ssh
pnpm run portal:bind:ssh
pnpm run portal:smoke:ssh
```

Historical `../../magick-ai/...` links in README were intentionally left in
place when they point to old archive plans or historical evidence.

## Verification Snapshot

The following checks passed during closeout:

```bash
bash -n dev/bootstrap-portal-site-dev.sh deploy/workspace-target.env.sh
pnpm run portal:bind:dev -- --site-id site_smoke --member-email portal-demo@example.com --skip-billing-rebuild
curl -sS http://127.0.0.1:8010/health/live
```

Portal dev-entry was verified to return `/portal` and set a portal session
cookie:

```bash
curl -i -c /tmp/npcink_portal_cookie.txt \
  'http://127.0.0.1:8010/portal/dev-entry?redirect=%2Fportal'
```

The portal session endpoint returned:

```text
site_admin_ref=site_admin:portal-demo@example.com
site_id=site_smoke
account_id=acct_site_smoke
auth_mode=jwt
```

Admin dev-entry was also verified to redirect to `/admin` and set an admin
session cookie.

## Current Local Baseline

The local development entry is:

```text
http://127.0.0.1:8010
```

Useful local entrypoints:

```text
http://127.0.0.1:8010/portal/dev-entry?redirect=%2Fportal
http://127.0.0.1:8010/admin/dev-entry?redirect=%2Fadmin
```

Current local Docker resources:

```text
npcink-ai-cloud-proxy-1
npcink-ai-cloud-frontend-1
npcink-ai-cloud-api-1
npcink-ai-cloud-postgres-1
npcink-ai-cloud-redis-1
```

Current Npcink volumes:

```text
npcink-ai-cloud_cloud-postgres-dev
npcink-ai-cloud_cloud-redis-dev
```

Old preserved volumes:

```text
magick-ai-cloud_cloud-postgres-dev
magick-ai-cloud_cloud-redis-dev
```

## Remaining Watch Items

- Keep the old `magick-ai-cloud_*` volumes until there is no chance that old
  local trial data is needed.
- Keep the SQL backup outside the repository.
- `.env` and `.env.local` are intentionally ignored. A fresh clone or another
  machine must recreate local development secrets and portal public URL
  settings.
- Do not rewrite historical archive docs solely to remove Magick-era paths.
  Clean only active commands, active runbooks, and current developer-facing
  instructions.

## New Feature Start Rule

New feature work can start from:

```bash
cd /Users/muze/gitee/npcink-ai-cloud
git switch master
git pull --ff-only
git switch -c codex/<feature-name>
```

If local portal access is needed after resetting the database, run:

```bash
pnpm run seed:smoke
pnpm run portal:bind:dev -- --site-id site_smoke --member-email portal-demo@example.com --skip-billing-rebuild
```
