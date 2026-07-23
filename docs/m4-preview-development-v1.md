# M4 Preview Development Workflow v1

## Decision

The authoring Mac remains the source and Git truth. The M4 is a disposable
Docker development runtime for build, execution, migration, tests, and preview.
No day-to-day Docker installation is required on the authoring Mac, and no Git
checkout or source edit is performed on M4.

The operator approved replacing the disposable legacy Cloud Preview rather than
keeping two Cloud stacks in parallel. The current defaults are:

| Boundary | Value |
| --- | --- |
| SSH transport | `muze@100.102.170.79` |
| M4 source mirror | `/Users/muze/docker-workspaces/npcink-ai-cloud-m4-dev` |
| Compose project | `npcink-ai-cloud-m4-dev` |
| Preview proxy | `127.0.0.1:8010` |
| PostgreSQL | `127.0.0.1:15433` |
| Redis | `127.0.0.1:16380` |
| Protected preview | `https://cloud.mqzjmax.top` |

This decision supersedes the earlier proposed parallel `8011` V2 rollout. It
does not authorize a production deploy or any
Cloudflare DNS, Access, or Tunnel change. The existing tunnel continues to use
`127.0.0.1:8010`.

## Safety Boundary

The checked-in defaults create, update, restart, or stop only the Compose
project `npcink-ai-cloud-m4-dev`. Explicit environment overrides remain
restricted to the `npcink-ai-cloud-m4-*` project and remote-directory family.
The legacy name `npcink-ai-cloud-m4-preview` is always rejected by the script,
so an ordinary command cannot accidentally mutate it.

Never use broad host cleanup commands such as `docker system prune`, broad
volume deletion, or deletion by a partial name. Other M4 Docker workloads are
outside this workflow.

All published ports bind to `127.0.0.1`. They are intentionally unreachable
through the M4 LAN or Tailscale address. Use the Cloudflare Access protected
domain for remote browser preview, or the checked-in SSH tunnel command for
local browser and WordPress-to-Cloud integration:

```bash
pnpm run m4:preview:tunnel
open http://127.0.0.1:18010
```

The tunnel binds only the authoring Mac's `127.0.0.1:18010`, stays in the
foreground, and closes with `Ctrl+C`. It does not update source, acquire the
remote deployment lock, or change containers. Use `-- --local-port <port>` or
`NPCINK_CLOUD_M4_TUNNEL_LOCAL_PORT` only when `18010` is already occupied.

`https://cloud.mqzjmax.top` remains the protected browser-preview entry. Do not
configure an automated local WordPress connector against that hostname:
Cloudflare Access returns a browser login redirect, while the connector requires
a non-redirecting JSON API response. For a disposable local WordPress
integration fixture, keep the tunnel open and use
`http://127.0.0.1:18010` as the self-hosted Cloud Base URL. Do not overwrite an
existing verified Cloud connection merely to exercise M4 Preview.

### Portal Test Account

After completing the Cloudflare Access challenge, open:

```text
https://cloud.mqzjmax.top/portal/dev-entry
```

The development-only entry creates a Portal session for
`portal-demo@example.com` and redirects to `/portal`. It does not require SMTP
or a Portal password. This is a shared development identity: every operator
allowed through the Cloudflare Access policy receives the same disposable
Portal account, so it must not contain personal, production, or otherwise
sensitive test data.

The entry remains gated twice: Cloudflare Access protects the public hostname,
and the frontend accepts the route only while `NEXT_PUBLIC_ENV=development` and
the request host is present in `NEXT_PUBLIC_MINI_DEV_HOST_ALLOWLIST`. It is not
a general user login path and must not be copied into a production Compose
environment.

To close domain auto-login without changing Cloudflare, remove
`cloud.mqzjmax.top` from `NPCINK_CLOUD_M4_MINI_DEV_HOST_ALLOWLIST` on M4 and
redeploy the preview. Removing the checked-in M4 override and redeploying is the
Git rollback.

## One-Time Environment Bootstrap

The source bundle never contains `.env`, `.env.local`, or `.env.deploy`.
Before the first deploy, initialize the remote directory and copy the existing
development environment files on M4 without printing their contents:

```bash
ssh muze@100.102.170.79 '
  set -eu
  install -d -m 700 /Users/muze/docker-workspaces/npcink-ai-cloud-m4-dev
  install -m 600 /Users/muze/gitee/npcink-ai-cloud/.env \
    /Users/muze/docker-workspaces/npcink-ai-cloud-m4-dev/.env
  install -m 600 /Users/muze/gitee/npcink-ai-cloud/.env.local \
    /Users/muze/docker-workspaces/npcink-ai-cloud-m4-dev/.env.local
'
```

Review those files on M4 when configuration changes are required. Do not copy
them back to the authoring Mac, add them to Git, or pass secret values on a
command line.

The M4 base-image prefetcher also requires `crane`:

```bash
ssh muze@100.102.170.79 \
  'HOMEBREW_NO_AUTO_UPDATE=1 brew install crane'
```

## Simplified Operating Model

M4 Preview is an integration runtime, not a mandatory inner loop.

1. **Ordinary local work:** edit and manage Git on the authoring Mac. Keep the
   local WordPress fixture local. Documentation, PHP-only, and other
   WordPress-only changes do not require an M4 sync.
2. **Cloud integration work:** sync only when the change needs the Cloud API,
   frontend, workers, PostgreSQL, or Redis. Open one foreground tunnel and use
   `http://127.0.0.1:18010` for both the browser and a disposable local
   WordPress fixture.
3. **Remote preview:** use `https://cloud.mqzjmax.top` only when the
   Cloudflare Access protected, off-machine browser path is the behavior being
   checked.

Do not add a second preview hostname, Cloudflare service-token storage in the
WordPress addon, a tunnel daemon, or another control plane to make this
single-operator development path more automatic.

Keep this model for five working days and record only:

- typical edit-to-preview time;
- minutes lost to network, tunnel, or synchronization failures each day;
- defects caught by the full M4 runtime that local WordPress work did not
  reveal.

Keep M4 as the default Cloud integration runtime when edit-to-preview normally
stays under two minutes and environment friction stays under ten minutes per
day. If those limits are repeatedly exceeded, use local Docker selectively for
the affected Cloud task and retain M4 as the integration/preview gate.

## Daily Commands

Run commands from the local repository worktree:

```bash
# Open one local-only browser and WordPress integration path
pnpm run m4:preview:tunnel

# First deployment or dependency/Dockerfile/lock-file change
pnpm run m4:preview:deploy

# Ordinary Python, frontend, migration, test, or documentation change
pnpm run m4:preview:sync

# Read-only runtime evidence
pnpm run m4:preview:status
pnpm run m4:preview:logs -- api
pnpm run m4:preview:logs -- --follow --tail 100 frontend

# Exact backend suites represented by check:fast
pnpm run m4:preview:test

# Start the existing project after a Docker Desktop or M4 restart
pnpm run m4:preview:recover

# Targeted lifecycle operations
pnpm run m4:preview:restart -- api
pnpm run m4:preview:stop
```

`deploy` builds the runtime and frontend images on M4. It never calls local
Docker and never relays a locally built image. `sync` refuses to continue when
a dependency input, Dockerfile, lock file, Compose file, or proxy configuration
requires `deploy`. `prepare` builds from an isolated incoming directory and
does not change the active source mirror, running containers, or deployed
fingerprint markers. If `prepare` produced newer images, `sync` refuses to
apply source until `deploy` has successfully validated those images.

The M4 Docker Desktop proxy currently truncates redirected registry blob
downloads. The M4-only builder therefore uses host-side `crane` to fetch the
arm64 base images directly into temporary archives and imports them into the
same M4 Docker engine. Python and Node are fetched through the DaoCloud Docker
Hub cache, while uv uses the Nanjing University GHCR cache. Both pinned inputs
must match the canonical digest, and the imported platform config digest is
verified before a local-only alias is created. The mutable Node tag's resolved
digest is cached alongside its imported config digest.

The backend build then validates and skips only the canonical external
Dockerfile-frontend declaration and uses Docker 29's bundled frontend, which
has been probed for the required secret-mount syntax. It substitutes only the
verified local base aliases in the streamed build recipes. Neither canonical
Dockerfile is edited, no image crosses from the authoring Mac, and production
build behavior is unchanged.

Build-container TLS is affected by the same Docker Desktop network path.
During an image rebuild, the deployment script starts a fixed-port
loopback-only package proxy on M4. It exposes only fixed PyPI, Python file, and
npm registry destinations through `host.docker.internal`, never forwards
client credentials, and is stopped before `prepare` or `deploy` returns. PyPI
configuration is passed as a BuildKit secret; the npm URL is a non-secret build
argument. The canonical Dockerfiles remain unchanged.

The frontend image already contains its pinned `node_modules`. M4 Preview starts
Next.js directly instead of performing an online install on every container
start. When the frontend image changes, deploy verifies the exact Compose
volume labels, removes only
`npcink-ai-cloud-m4-dev_cloud-frontend-node-modules-dev`, and lets Docker copy
the new image dependencies into that disposable volume. PostgreSQL, Redis,
artifacts, and unrelated M4 volumes are never part of this refresh.

The overlay explicitly marks the frontend as development and uses the
repository's development-only completed-installation override. This keeps the
first-install gate from asking the development API for production setup state;
it does not alter the production setup contract or production Compose.

The API uses Uvicorn reload for `app/**` and migrations. Next.js development
mode handles ordinary frontend changes. Runtime, callback, and ops workers are
restarted after every successful sync because they do not have file watchers.

The M4 currently has no host Node or pnpm runtime. `m4:preview:test` therefore
runs `pytest tests/contract` followed by `pytest tests/domain` in the M4 API
image. These are the two exact suites behind `pnpm run check:fast`; the command
prints that equivalence before it runs them.

## Source Synchronization Contract

Each operation packages:

- Git-tracked files that still exist in the worktree;
- non-ignored untracked files that are eligible for preview.

It excludes Git metadata, all `.env*` files except `.env.example`,
`node_modules`, `frontend/.next`, `.venv`, test and language caches,
`.runtime`, build outputs, deployment-secret directories, and browser-test
outputs. The remote `.env` and `.env.local` are protected from both overwrite
and `rsync --delete`.

After a successful deployment, status records:

- source commit and branch;
- clean or dirty state and dirty path count;
- source bundle SHA-256;
- dependency and runtime-config fingerprints;
- runtime and frontend image IDs and creation times;
- Alembic revision and deployment UTC time.

This metadata is evidence, not a second source-control system.

## First Replacement Procedure

Use `prepare` once to build images and validate the new Compose model while the
legacy `8010` stack is still running:

```bash
pnpm run m4:preview:prepare
```

`prepare` unpacks the source into an isolated staging directory and builds on
M4, but does not change the active source mirror, containers, or deployed
fingerprint markers.
Immediately before releasing the old port, re-check the legacy project's
Compose labels, published ports, and named volumes. Then remove only
`npcink-ai-cloud-m4-preview`. The old database and Redis volumes are
disposable by operator decision; no data migration or volume reuse is allowed.

Start the replacement with:

```bash
pnpm run m4:preview:deploy
pnpm run m4:preview:test
pnpm run m4:preview:status
```

Do not remove the old project until `prepare` succeeds. Do not change the
Cloudflare tunnel during this replacement: both stacks use the same loopback
origin at different times.

## Health and Exposure Verification

Expected checks on M4:

```bash
curl -fsS http://127.0.0.1:8010/health/live
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8010/
docker ps --format '{{.Names}} {{.Ports}}'
docker inspect npcink-ai-cloud-m4-dev-api-1 \
  --format '{{.HostConfig.RestartPolicy.Name}}'
```

Expected results are HTTP `200`, exact loopback-only port bindings, and
`unless-stopped` for every long-running service. From a separate machine,
requests to `192.168.10.200:8010`, `100.102.170.79:8010`, and the corresponding
database and Redis ports must fail.

The proxy deliberately hides `/docs`, readiness/operational diagnostics, and
`/internal/**` from the preview origin. Its access log records URI paths but not
query strings. The log command redacts values loaded from the protected env
files, authorization/cookie fields, credentialed URLs, PEM blocks, and common
secret-shaped fields before bytes leave M4.

## Restart Recovery

Every service uses `restart: unless-stopped`. The 2026-07-23 M4 acceptance
reboot on Docker Desktop 4.83.0 preserved all containers, images, and volumes,
but left the containers in an exited state. This matches
[Docker's documented `unless-stopped` behavior](https://docs.docker.com/engine/containers/start-containers-automatically/)
when a container is already stopped during a graceful host shutdown.

After Docker Desktop or M4 restarts, inspect the actual running and exited
containers with:

```bash
pnpm run m4:preview:status
```

If all eight existing containers are exited, recover them without rebuilding
images or synchronizing source:

```bash
pnpm run m4:preview:recover
```

`recover` refuses to continue if any expected container is missing. Use
`m4:preview:deploy` in that case so source, migrations, images, ports, and
health are validated together.

For a non-disruptive policy check, inspect all eight services through status.
For a deliberate recovery drill, restart Docker Desktop or the M4 only during a
maintenance window, wait for Docker to become ready, then run status, recover,
and repeat both HTTP checks.

An intentional `m4:preview:stop` suppresses automatic restart until the next
`m4:preview:recover` or `m4:preview:deploy`.

## Failure and Rollback

Deployment and lifecycle operations use an atomic remote directory lock. A
failed deploy stops only the new project's application, frontend, proxy, and
workers; it does not issue broad Docker cleanup.

To contain a broken replacement:

```bash
pnpm run m4:preview:stop
```

To roll source back, use a clean local worktree at the
last known-good Git revision. Run `pnpm run m4:preview:deploy` from that
worktree.
To destroy the disposable replacement, first resolve its exact Compose labels
and directory, then run `docker compose down --volumes --remove-orphans` with
the exact `npcink-ai-cloud-m4-dev` project name. This destructive step is an
operator action, not part of the daily script.

If an operation reports a stale lock, inspect
`~/.cache/npcink-ai-cloud-m4-dev/operation.lock/owner.txt` and confirm that no
deploy, sync, test, restart, or stop process is active before removing only that
lock directory.
