# Workspace Target

This file records the current workspace-specific remote deploy target for
Npcink AI Cloud so future AI sessions do not need to recover it from chat
history.

## Confirmed values

- Remote host IP: read from `NPCINK_CLOUD_DEPLOY_SSH_HOST`
- Remote domain: `magick.sofile.cn`
- SSH user: `root`
- SSH identity file:
  `../../config/key/Magick_AI.pem`
- Local SSL cert source:
  `../../config/magick.sofile.cn_nginx-ssl/`
- Confirmed public base URL target: `https://magick.sofile.cn`
- Remote deploy root exists: `/opt/npcink-ai-cloud`
- Current host-nginx bind status:
  - `magick.sofile.cn` DNS A -> current `NPCINK_CLOUD_DEPLOY_SSH_HOST`
  - system `nginx` now listens on `80/443` and proxies to `127.0.0.1:8010`
  - local-on-server `curl -k https://127.0.0.1/health/live` reaches Cloud successfully
  - public `http://magick.sofile.cn/*` works and redirects to `https://...`
  - public `https://magick.sofile.cn/*` had already been verified reachable before the first remote Authentik bootstrap
- Current remote provider mode: OpenAI provider is configured against
  `https://api.deepseek.com/v1`
- Current remote `.env.deploy` already contains active internal auth and provider
  credentials; local `cloud/.env.deploy` has been synced from the remote target
  for workspace handoff

## Saved launcher file

- Shell exports: `cloud/deploy/workspace-target.env.sh`
- Deploy env template: `cloud/.env.deploy`
- Host nginx bind helper: `cloud/deploy/bind-domain-to-ssh-host.sh`

Load it with:

```bash
source cloud/deploy/workspace-target.env.sh
```

## Current deploy loop

Local inner loop:

```bash
pnpm run cloud:test
pnpm run check:cloud:perimeter
pnpm run smoke:local-alpha
```

Bundle replay before remote deploy:

```bash
pnpm run check:e2e:cloud-deploy-bundle:smoke
```

Fast remote iteration after local checks pass:

```bash
source cloud/deploy/workspace-target.env.sh
pnpm run cloud:deploy:ssh -- --skip-bundle-build --skip-seed
```

If only env values changed:

```bash
source cloud/deploy/workspace-target.env.sh
pnpm run cloud:env:ssh
```

## Current release verification

- `pnpm run check:e2e:cloud-deploy-bundle:smoke` -> passed
- `pnpm run cloud:deploy:ssh` -> passed
- `GET ${NPCINK_CLOUD_BASE_URL}/health/live` -> `200 OK`
- `GET ${NPCINK_CLOUD_BASE_URL}/` -> buyer-facing home page present
- `GET ${NPCINK_CLOUD_BASE_URL}/portal/login` -> portal login present

Formal release gating now follows:

- `cloud/deploy/RELEASE_CHECKLIST.md`

Current remote portal verification commands:

```bash
source cloud/deploy/workspace-target.env.sh
pnpm run cloud:portal:bind:ssh -- --site-id <site-id> --member-email <email>
pnpm run cloud:portal:smoke:ssh -- --site-id <site-id> --member-email <email>
```

Dev-only development-code verification now uses a separate helper under
`deploy/dev/`:

```bash
source cloud/deploy/workspace-target.env.sh
bash deploy/dev/remote-portal-login-code-smoke.sh --site-id <site-id> --member-email <email>
```

Preferred real-site portal verification commands:

```bash
source cloud/deploy/workspace-target.env.sh
pnpm run cloud:portal:bind:ssh -- --site-id <site-id> --member-email <email>
pnpm run cloud:portal:smoke:ssh -- --site-id <site-id> --member-email <email>
```

Short runbook:

- `docs/archive/plans/cloud-mvp-ops-runbook.md`
- `docs/archive/plans/cloud-mvp-acceptance-receipt-2026-03-23.md`

Portal verification should always use explicit real-site bootstrap and the
portal smoke helper.
