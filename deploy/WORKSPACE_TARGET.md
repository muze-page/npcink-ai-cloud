# Workspace Target

This file records the current workspace-specific remote deploy target for
Npcink AI Cloud so future AI sessions do not need to recover it from chat
history.

## Confirmed values

- Remote host IP: read from `NPCINK_CLOUD_DEPLOY_SSH_HOST`
- Current remote host IP: `120.24.237.214`
- Remote domain: `cloud.npc.ink`
- SSH user: `root`
- SSH credential: operator-held production secret; do not store the password in
  this repository. If key-based SSH is used, set
  `NPCINK_CLOUD_DEPLOY_IDENTITY_FILE` outside Git or in a local-only env file.
- Confirmed public base URL target: `https://cloud.npc.ink`
- Remote deploy root exists: `/opt/npcink-ai-cloud`
- Current domain status:
  - `cloud.npc.ink` is the production public origin.
  - `GET https://cloud.npc.ink/health/live` was verified reachable from this
    workstation on 2026-07-06.
  - `magick.sofile.cn` and host `114.132.150.46` are historical targets and
    should not be used for new Cloud deployment or smoke commands.
- Current remote provider mode: OpenAI provider is configured against
  `https://api.deepseek.com/v1`
- Current remote `.env.deploy` should remain server-side or in the deploy secret
  store. Do not commit production tokens, provider keys, DB credentials, SSH
  credentials, or `.env.deploy`.

## Saved launcher file

- Shell exports: `deploy/workspace-target.env.sh`
- Deploy env template: `.env.deploy`
- Host nginx bind helper: `deploy/bind-domain-to-ssh-host.sh`

Load it with:

```bash
source deploy/workspace-target.env.sh
```

The launcher exports only non-secret target metadata. Password-based SSH must
be supplied by the operator at connection time or managed outside Git.

## Current deploy loop

Local inner loop:

```bash
pnpm run test
pnpm run check:perimeter
pnpm run smoke:local-alpha
```

Bundle replay before remote deploy:

```bash
pnpm run check:e2e:deploy-bundle:smoke
```

Fast remote iteration after local checks pass:

```bash
source deploy/workspace-target.env.sh
pnpm run deploy:ssh -- --skip-bundle-build --skip-seed
```

If only env values changed:

```bash
source deploy/workspace-target.env.sh
pnpm run env:ssh
```

## Current release verification

- `pnpm run check:e2e:deploy-bundle:smoke` -> passed
- `pnpm run deploy:ssh` -> passed
- `GET ${NPCINK_CLOUD_BASE_URL}/health/live` -> `200 OK`
- `GET ${NPCINK_CLOUD_BASE_URL}/` -> buyer-facing home page present
- `GET ${NPCINK_CLOUD_BASE_URL}/portal/login` -> portal login present

Formal release gating now follows:

- `deploy/RELEASE_CHECKLIST.md`

Current remote portal verification commands:

```bash
source deploy/workspace-target.env.sh
pnpm run portal:bind:ssh -- --site-id <site-id> --member-email <email>
pnpm run portal:smoke:ssh -- --site-id <site-id> --member-email <email>
```

Dev-only development-code verification now uses a separate helper under
`deploy/dev/`:

```bash
source deploy/workspace-target.env.sh
bash deploy/dev/remote-portal-login-code-smoke.sh --site-id <site-id> --member-email <email>
```

Preferred real-site portal verification commands:

```bash
source deploy/workspace-target.env.sh
pnpm run portal:bind:ssh -- --site-id <site-id> --member-email <email>
pnpm run portal:smoke:ssh -- --site-id <site-id> --member-email <email>
```

Short runbook:

- `docs/archive/plans/cloud-mvp-ops-runbook.md`
- `docs/archive/plans/cloud-mvp-acceptance-receipt-2026-03-23.md`

Portal verification should always use explicit real-site bootstrap and the
portal smoke helper.
