# Production GitHub Deploy

This repository uses `production` as the production release source for
`https://cloud.npc.ink`. Protect the branch when the GitHub plan/repository
visibility supports branch protection rules.

The current early-validation process gate is
[`docs/cloud-production-release-policy-v1.md`](../docs/cloud-production-release-policy-v1.md).
Run it locally with:

```bash
pnpm run check:release-policy
```

## Branch Model

- `master`: development integration branch.
- `production`: production release branch.
- feature branches: merge into `master` first, then promote to `production`.

Do not edit production application code directly on the server. Production
server edits are limited to runtime secrets and emergency break-glass fixes that
are immediately backported to Git.

## GitHub Actions

`Cloud CI` runs on `master`, `main`, and `production`.

On `production` push events, `Cloud CI` runs `backend` and `frontend` first,
then runs the `deploy-production` job only after both pass. `Deploy Production`
is a manual fallback workflow only, and must be run from the `production`
branch. The deploy jobs are bound to the GitHub Environment named `production`;
add environment approval rules when the GitHub plan supports them.

The production deploy job:

1. Builds the production Docker image bundle.
2. Uploads a new release to the SSH host.
3. Reuses the existing server-side `.env.deploy`.
4. Starts `docker-compose.runtime.yml`.
5. Runs migrations.
6. Refreshes provider catalog and provider health.
7. Verifies `/health/operational-ready`.

## GitHub Secrets

Configure these repository or environment secrets:

```text
PROD_SSH_HOST=120.24.237.214
PROD_SSH_USER=deploy
PROD_SSH_PORT=22
PROD_SSH_KEY=<private key for deploy user>
PROD_REMOTE_DIR=/opt/npcink-ai-cloud
PROD_BASE_URL=https://cloud.npc.ink
```

Keep production runtime secrets on the server in:

```text
/opt/npcink-ai-cloud/current/.env.deploy
```

Do not put database passwords, SMTP passwords, provider API keys, portal JWT
secrets, or internal auth tokens in GitHub Actions unless you intentionally move
to a managed secret store.

## Production Runtime Shape

`docker-compose.runtime.yml` is the low-memory production runtime:

- `postgres`
- `redis`
- `api`
- `frontend`
- `worker`
- `callback-worker`
- `ops-worker`
- `proxy`
- `caddy`

It omits local/development observability sidecars. Caddy owns public `80/443`
and proxies to the internal Docker proxy. The app proxy binds `8010` only on
`127.0.0.1`.

## Promotion Flow

```text
local feature work
  -> PR to master
  -> Cloud CI passes
  -> PR master -> production
  -> Cloud CI passes on production
  -> GitHub Environment approval, when available
  -> Cloud CI deploy-production job
  -> operational-ready passes
```

Runtime configuration-only changes can be applied to the server `.env.deploy`
and followed by a container restart. Code, policy, billing, governance, and
provider routing logic changes must go through Git.
