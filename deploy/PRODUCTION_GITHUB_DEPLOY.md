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

`Cloud CI` runs on pull requests, `master`, `main`, and `production`.

Pull requests use a targeted backend gate by default: release-policy contract,
anti-drift checks, changed Python quality, contract tests, and changed pytest
files. High-risk backend surfaces still escalate to the full backend gate. Pushes
to `master`, `main`, and `production` continue to run full Ruff, Mypy, and
`tests/api tests/contract tests/domain` before release promotion or deploy.

On `production` push events, `Cloud CI` runs `backend` and `frontend` first,
then runs the `deploy-production` job only after both pass. `Deploy Production`
is a manual fallback workflow only, and must be run from the `production`
branch. The deploy jobs are bound to the GitHub Environment named `production`;
add environment approval rules when the GitHub plan supports them.

Exception: if a `production` push changes only `site/terms/*`, `Cloud CI` uses
the static terms fast path. That path skips backend/frontend/full Docker
deployment, uploads only the checked-in `site/terms` tree to the current release,
and verifies `/terms`, `/terms/en/terms.html`, `/terms/zh/terms.html`,
`/terms/styles.css`, and `/health/live`.

The production deploy job:

1. Builds the production Docker image bundle.
2. Uploads a new release to the SSH host.
3. Reuses the existing server-side `.env.deploy`.
4. Starts `docker-compose.runtime.yml`.
5. Runs migrations.
6. Refreshes provider catalog and provider health.
7. Verifies `/health/operational-ready`.
8. Verifies public static legal pages, including `/terms/en/terms.html`.

By default the bundle contains only the app image, the optional frontend image,
deploy scripts, compose files, and static site files. Worker, callback-worker,
and ops-worker services reuse the app image and are tagged on the release host.
External service images such as Postgres, Redis, nginx, OTEL Collector, and
Jaeger are not repackaged on every deploy; the host should already have them or
allow Docker Compose to pull them by pinned tag.

For offline or first-host bootstrap bundles, set:

```bash
NPCINK_CLOUD_INCLUDE_EXTERNAL_IMAGES=1
```

The GitHub deploy path also enables BuildKit GitHub Actions cache for app and
frontend Docker builds.

After each release, capture job timing with:

```bash
pnpm run release:timing -- <github-actions-run-id>
pnpm run release:timing --from-file /tmp/github-run.json
```

Use the report to separate approval wait time from actual CI, bundle upload, and
remote readiness time. `gh pr checks` can show long-running jobs as `pending 0`;
prefer this timing report or `gh run view --json jobs` when comparing release
duration.

The static terms fast path runs:

```bash
pnpm run deploy:static-terms:ssh
```

Use it only for public static legal/policy page content under `site/terms/*`.
Any proxy, compose, application, API, provider, database, or runtime change must
use the full production deploy path.

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
`127.0.0.1`. Public legal and policy pages under `/terms/*` are served as
static files from the checked-in `site/` directory by the production proxy.

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
