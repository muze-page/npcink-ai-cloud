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
files. High-risk backend surfaces escalate to the full backend gate. Pushes to
`master`, `main`, and `production` also use the full backend gate before release
promotion or deploy.

The public backend release check remains named `backend`, but it is an aggregate
gate. It depends on backend scope classification, the targeted PR gate when a
targeted gate is enough, or the full backend path split into `backend-static`
and three `backend-pytest` shards when the full gate is required. The pytest
shards are selected from `ci/pytest-backend-durations.json`, which is generated
from real JUnit timing artifacts rather than hand-picked test names.

Full backend runs upload `pytest-backend-timing-shard-*` artifacts containing
each shard's JUnit report and selected file list, then write slow-test tables to
the job summary.

On `production` push events, `Cloud CI` runs `backend` and `frontend` first,
then runs the `deploy-production` job only after both pass. `Deploy Production`
is a manual fallback workflow only, and must be run from the `production`
branch. The deploy jobs are bound to the GitHub Environment named `production`;
add environment approval rules when the GitHub plan supports them.
After a successful production deploy, `Cloud CI` runs `post-production-smoke`.
That job runs the small-customer preflight automatically. It runs the formal
release smoke too when the optional release-smoke secrets are configured; if
they are missing, the job summary records the skip without printing secret
values.

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
pnpm run release:junit-timing -- artifacts/pytest-backend-shard-1.xml
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

Optional formal release-smoke secrets for automatic `post-production-smoke`:

```text
NPCINK_CLOUD_INTERNAL_AUTH_TOKEN=<internal readiness token>
NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN=<admin bootstrap token>
NPCINK_CLOUD_RELEASE_MEMBER_EMAIL=<invited release member email>
NPCINK_CLOUD_PORTAL_LOGIN_CODE=<one valid release login code>
NPCINK_CLOUD_RELEASE_SITE_ID=<runtime smoke site id>
NPCINK_CLOUD_RELEASE_KEY_ID=<runtime smoke key id>
NPCINK_CLOUD_RELEASE_KEY_SECRET=<runtime smoke key secret>
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
The frontend does not load `.env.deploy`; it receives only its explicit runtime
allowlist, including the server-side internal token required by the existing
admin proxy. Runtime-data encryption, bootstrap, admin-session,
service-settings, Portal JWT, database, and provider secrets stay in backend
containers only.

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

Runtime configuration-only changes can normally be applied to the server
`.env.deploy` and followed by a container restart. This does not apply to
`NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET` or
`NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID`: never rotate either through the
ordinary deploy path because existing ciphertext must be re-encrypted while all
four writers are stopped. Code, policy, billing, governance, and provider
routing logic changes must go through Git.

## One-Time Runtime-Data Encryption Maintenance

This maintenance path is deliberately separate from the normal deployment
sequence above; it does not change the generic deploy scripts or their order.

Before the cutover, extract and load the bundle into a staged release without
switching `current`. A pure bundle does not contain `.env.deploy`; before any
Compose command, copy the protected shared file into the staged directory and
verify its permissions, falling back to the current release copy only when the
shared file is absent:

```bash
cd /opt/npcink-ai-cloud/releases/STAGED_RELEASE
umask 077
ENV_SOURCE=/opt/npcink-ai-cloud/.env.deploy
if [ ! -f "${ENV_SOURCE}" ]; then
  ENV_SOURCE=/opt/npcink-ai-cloud/current/.env.deploy
fi
test -f "${ENV_SOURCE}"
install -m 600 "${ENV_SOURCE}" ./.env.deploy
test "$(stat -c '%a' ./.env.deploy)" = "600"
```

Do not call `deploy/deploy-to-ssh-host.sh`,
`deploy/remote-load-and-up.sh`, or another general deploy helper to prepare the
staged release; those paths switch `current` and/or start services before
re-encryption verification. Preserve a checksum-verified custom-format database backup,
verify restoration into a separate database, and retain the matching old code
revision and old key material. Keep the production `postgres` and `redis`
services running, stop and fence `api`, `worker`, `callback-worker`, and
`ops-worker`, and create a `0600` untracked maintenance env containing:

```text
NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET=<target-secret>
NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID=<target-key-id>
NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET=<old-root-secret>
```

From the staged release directory, run every phase inside the newly loaded API
image. The host does not need application source or a Python environment:

```bash
docker compose --env-file .env.deploy -f docker-compose.runtime.yml \
  run --rm --no-deps --env-from-file "${MAINTENANCE_ENV}" api \
  python -m app.dev.reencrypt_runtime_data inventory
docker compose --env-file .env.deploy -f docker-compose.runtime.yml \
  run --rm --no-deps --env-from-file "${MAINTENANCE_ENV}" api \
  python -m app.dev.reencrypt_runtime_data dry-run \
    --old-root-env NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET
docker compose --env-file .env.deploy -f docker-compose.runtime.yml \
  run --rm --no-deps --env-from-file "${MAINTENANCE_ENV}" api \
  python -m app.dev.reencrypt_runtime_data apply \
    --confirm-maintenance-window \
    --old-root-env NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET
docker compose --env-file .env.deploy -f docker-compose.runtime.yml \
  run --rm --no-deps --env-from-file "${MAINTENANCE_ENV}" api \
  python -m app.dev.reencrypt_runtime_data verify
```

The first raw-ciphertext cutover omits `--old-key-id`. For future `rde.v1` to
`rde.v1` rotation, inventory declares the old key ID alone, while `dry-run` and
`apply` pair that same ID positionally with the old root:

```bash
export OLD_RUNTIME_DATA_KEY_ID=rde-previous-key-id
docker compose --env-file .env.deploy -f docker-compose.runtime.yml \
  run --rm --no-deps --env-from-file "${MAINTENANCE_ENV}" api \
  python -m app.dev.reencrypt_runtime_data inventory --old-key-id "${OLD_RUNTIME_DATA_KEY_ID}"
docker compose --env-file .env.deploy -f docker-compose.runtime.yml \
  run --rm --no-deps --env-from-file "${MAINTENANCE_ENV}" api \
  python -m app.dev.reencrypt_runtime_data dry-run \
    --old-root-env NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET \
    --old-key-id "${OLD_RUNTIME_DATA_KEY_ID}"
docker compose --env-file .env.deploy -f docker-compose.runtime.yml \
  run --rm --no-deps --env-from-file "${MAINTENANCE_ENV}" api \
  python -m app.dev.reencrypt_runtime_data apply \
    --confirm-maintenance-window \
    --old-root-env NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET \
    --old-key-id "${OLD_RUNTIME_DATA_KEY_ID}"
```

Add multiple old-root/key-ID pairs only with preflight evidence.

Do not restart writers unless the new-key-only verification succeeds. Start
`api` and verify readiness first, then start the three workers and verify
operational readiness before restoring frontend/proxy traffic. Remove temporary
old-key material and the `0600` maintenance env after the evidence window.
Normal runtime has no legacy or dual-read path; retain the migration-only tool
for future controlled rekeys.

Rollback requires the matching old database backup, old application revision,
and old key together. Once new-key writes exist, restoring only the environment
or only the code is not a valid rollback. The authoritative operator procedure
is `deploy/OPS_PLAYBOOK.md`.
