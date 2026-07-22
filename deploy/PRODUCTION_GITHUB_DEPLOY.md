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

Do not edit production application code directly on the server. `.env.deploy`
contains only reviewed non-secret deployment/runtime settings. Protected
structured configuration under `shared/config/` is changed only by `/setup` or
the governed setup/admin-key rotation helpers. Emergency break-glass fixes must
be immediately backported to Git.

## GitHub Actions

`Cloud CI` runs on pull requests, `master`, `main`, and `production`. A push to
`production` validates source truth only; it never deploys the host.

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

Ordinary production deployment has one trigger: manually dispatch
`Deploy Production` from the exact `production` revision after `Cloud CI` is
green. The operator must enter
`Approved for production validation by operator.` exactly, and the GitHub
Environment named `production` must receive its human approval. The workflow
then deploys and runs the small-customer preflight plus optional formal release
smoke. Missing optional smoke secrets produce an explicit skip, never a
secret-bearing log. Neither a normal `production` push nor a static-terms-only
push deploys automatically. The only temporary exception is the exact
bundle-bound trusted-workstation path for the current empty-host PostgreSQL 18
first install described below; it is not reusable after finalization.

`Deploy Production` and `Production Maintenance` share the
`production-host-mutation` concurrency group. A mutating `safe-prune` also
requires the exact phrase `Prune production images and old releases.` and
atomically acquires the same remote `.deploy-lock` used by deployment. It must
never prune images or releases while another host mutation holds that lock.

The manually approved production deploy job:

1. Builds the production Docker image bundle.
2. Uploads the exact bundle and, when supplied, the env file as separate
   protected incoming objects. The release payload never contains `.env.deploy`.
3. Installs the selected env source at
   `${REMOTE_DIR}/.release-state/<release-name>/env.deploy`; the two state
   directories are mode `0700` and the env file is mode `0600`.
4. Resolves both old and new Compose project names, verifies the actual old
   writer labels, and rejects drift before the first image or container mutation.
5. Runs the explicit `prepare-only` phase, which loads and proves exact images,
   writes the mode-`0600` fixed target-daemon map at
   `${REMOTE_DIR}/.release-state/<release-name>/target-daemon-images.json`, and
   starts no service.
6. Uses the exact candidate API image to load protected runtime configuration,
   prove private-name/TLS connectivity to PostgreSQL 18, and accept exactly one
   Alembic revision at the candidate head or a known ancestor. This preflight
   completes before old public/write services stop.
7. Stops the old public/write services and records the writer cutoff.
8. Runs the explicit `data-only` phase to create, prove, and start only Redis
   by target-daemon image ID. PostgreSQL is external Alibaba RDS 18 and is never
   a formal Compose service or bundled image.
9. Runs the external RDS migration and provider refresh through staged one-off
   API containers with Runtime Compose `pull_policy: never` and exact image-ID
   proof, then requires the database to expose the exact sole candidate head.
10. Moves `current` atomically, then runs `api-only` to start and verify API.
11. Runs `workers-only`, proves each new worker container is stable, and proves
   each heartbeat is newer than the cutover cutoff, then verifies generic
   `/health/operational-ready`.
12. Runs `traffic-only` to restore frontend/proxy traffic and verifies public
    static legal pages, including `/terms/en/terms.html`.

The exact bundle contains the application outputs, the optional frontend output,
deploy scripts, Compose files, static site files, and every locked external
runtime image when external images are enabled. Worker, callback-worker, and
ops-worker services reuse the app image and are tagged on the release host. The
only locked external runtime inputs are Redis and NGINX; Caddy, Jaeger, and the
OpenTelemetry Collector are not part of the release bundle or image lock.
Secret/config state is external to that payload and must not be added to its
archive manifest.

`--skip-frontend-image` preserves an existing frontend only. It fails before
mutation when there is no previous managed release or no single running
frontend to preserve; it is never a first-deploy shortcut.

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
The helper uploads a root-owned mode-`0600` archive under a unique
`.incoming/static-terms.<token>.tgz` name, acquires the same remote
`.deploy-lock` as the full deployment, and resolves `current` exactly once to a
direct managed `release-*` directory. It stages and validates the replacement,
moves the prior tree to `terms.previous`, activates only inside that frozen
release, and keeps the lock until the public terms pages and `/health/live`
pass. A pre-commit failure restores the prior tree (or the original absence),
cleans the protected upload, and records mode-`0600` failure evidence. Cleanup
or unlock failure returns nonzero and retains the shared lock and evidence for
operator recovery; it never reports a false success. Any proxy, compose,
application, API, provider, database, or runtime change must use the full
production deploy path.

## GitHub Secrets

Configure these repository or environment secrets:

```text
PROD_SSH_HOST=120.24.237.214
PROD_SSH_USER=root
PROD_SSH_PORT=22
PROD_SSH_KEY=<private key for the root-managed release account>
PROD_SSH_KNOWN_HOSTS=<pinned known_hosts line verified through an independent channel>
PROD_REMOTE_DIR=/opt/npcink-ai-cloud
PROD_BASE_URL=https://cloud.npc.ink
```

Optional formal release-smoke secrets used by the manually dispatched deploy:

```text
NPCINK_CLOUD_INTERNAL_AUTH_TOKEN=<internal readiness token>
NPCINK_CLOUD_ADMIN_KEY=<operator-only admin key>
NPCINK_CLOUD_RELEASE_MEMBER_EMAIL=<invited release member email>
NPCINK_CLOUD_PORTAL_LOGIN_CODE=<one valid release login code>
NPCINK_CLOUD_RELEASE_SITE_ID=<runtime smoke site id>
NPCINK_CLOUD_RELEASE_KEY_ID=<runtime smoke key id>
NPCINK_CLOUD_RELEASE_KEY_SECRET=<runtime smoke key secret>
```

Keep generated database credentials and runtime security roots outside both the
release payload and `.env.deploy`, under the protected shared config root. The
matching per-release state remains for non-secret deploy inputs and image
evidence:

```text
/opt/npcink-ai-cloud/.release-state/<release-name>/env.deploy
/opt/npcink-ai-cloud/.release-state/<release-name>/target-daemon-images.json
/opt/npcink-ai-cloud/shared/config/runtime-config.json
/opt/npcink-ai-cloud/shared/config/install-state.json
```

`/opt/npcink-ai-cloud/current` selects code only. Its basename selects the
corresponding protected state directory. Both `.release-state` and its release
child are owner-controlled non-symlink directories with mode `0700`;
`env.deploy` and `target-daemon-images.json` are owner-controlled regular files
with mode `0600`. The target-daemon map path is derived from the managed release
basename and cannot be overridden. A separately uploaded env is staged under
the protected incoming directory and installed here before Compose runs; it is
never extracted into the release directory.

Do not put database passwords, SMTP passwords, provider API keys, or generated
runtime roots in GitHub Actions. The internal token and admin key appear in the
formal smoke secret list only as explicit operator-controlled test credentials;
they are never runtime `.env.deploy` inputs.

## Production Host Prerequisites

The production SSH secret must identify the root-managed release account; do
not fall back to a guessed `deploy` user. All managed paths under
`/opt/npcink-ai-cloud` are `root:root` and must not be group- or world-writable.
Before the current first installation, normalize and verify that tree, then create
`/var/backups/npcink-ai-cloud` and `/run/npcink-ai-cloud` as root-owned mode
`0700` directories.

The production Environment must also hold a pre-verified
`PROD_SSH_KNOWN_HOSTS` entry for the exact host/port. Obtain and compare its
fingerprint through an independent trusted channel before storing it. The
workflow never uses runtime `ssh-keyscan` as a trust root, and all SSH/SCP
connections require `StrictHostKeyChecking=yes`. A legitimate host-key change
must be investigated and the pinned secret deliberately rotated before deploy.

Host release tools use
`NPCINK_CLOUD_RELEASE_TOOL_PYTHON=/usr/bin/python3.11` and require Python
`>=3.11`. Cloud application code is different: it runs inside the exact image
and requires Python `>=3.12`. Configure
`NPCINK_CLOUD_DEPLOY_HOST_PYTHON=/usr/bin/python3.11`, or pass
`--host-python /usr/bin/python3.11`. The SSH entry point verifies that host
interpreter before any remote mkdir, upload, or deployment lock.

## Production Runtime Shape

`docker-compose.runtime.yml` is the low-memory production runtime. PostgreSQL
is the configured external Alibaba RDS 18 instance and is intentionally absent:

- `redis`
- `api`
- `frontend`
- `worker`
- `callback-worker`
- `ops-worker`
- `proxy`

The trusted request chain is `external Edge -> bundled NGINX -> Gunicorn`.
The operator-owned Edge owns public `80/443`, certificates, TLS policy, DNS,
and any WAF/source restrictions. The Cloud bundle publishes no public `80/443`;
NGINX binds `8010` only on `127.0.0.1`. Runtime Compose requires all of the
following before it is a valid production entry point:

```text
NPCINK_CLOUD_EXTERNAL_EDGE_READY=true
NPCINK_CLOUD_BASE_URL=https://cloud.npc.ink
NPCINK_CLOUD_DOMAIN_NAME=cloud.npc.ink
```

The base URL must use HTTPS and its host must exactly match
`NPCINK_CLOUD_DOMAIN_NAME`.
The external Edge must replace inbound `X-Real-IP`, `X-Forwarded-For`,
`X-Forwarded-Proto`, `X-Forwarded-Host`, and `X-Forwarded-Port` values. NGINX
trusts real-client headers only from the gateway recorded in the protected
per-release runtime network state; Gunicorn trusts forwarded headers only from
the proxy IPv4 address in that same state. The `172.28.0.1` gateway and
`172.28.0.10` proxy are fresh-network defaults, not authority for an existing
managed Compose network.

Public legal and policy pages under `/terms/*` are served as static files from
the checked-in `site/` directory by NGINX.
The frontend does not load `.env.deploy`; it receives only its explicit runtime
allowlist, including the server-side internal token required by the existing
admin proxy. `api`, `worker`, `callback-worker`, and `ops-worker` each receive
both the Service Settings target root/key-ID pair and the Runtime Data target
root/key-ID pair. `frontend` receives none of those four variables.
Runtime-data encryption, bootstrap, admin-session, service-settings, Portal
JWT, database, and provider secrets stay in backend containers only.

Production Compose does not run a trace collector or trace store. OTLP export
is optional for ordinary runtime operation. Formal release requires explicit,
operator-owned `NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT` and
`NPCINK_CLOUD_OTEL_TRACE_QUERY_URL` values and evidence that a fresh Cloud trace
is queryable.

The exact-bundle smoke is the formal release workflow's plain-HTTP exception:
it may replay the artifact through loopback NGINX without an external Edge.
Never use that local smoke topology as a production public origin.

### Historical external-Edge P1-E06 procedure (non-normative)

The following external-Edge procedure records the retired P1-E06 activation.
It is not a current first-install or ordinary-deploy database contract.

P1-E06 treated the external Edge as an independent hard gate. Before invoking
the cutover, the governed Edge migration must install and activate host NGINX,
pass `nginx -t` and the exact-host loopback-resolved HTTPS check, stop the
retired project Caddy, and complete the certificate-readiness evidence. It must
also record a named
certificate-renewal owner, enable an automatic renewal service/timer, pass a
renewal dry run plus direct persistent hook/reload test, and prove at least 30
days of validity for both the named PEM and the leaf served on
`127.0.0.1:443`; their SHA256 fingerprints must match. The hook must be a
root-owned non-writable executable directly under `renewal-hooks/deploy`. On
Alibaba Cloud Linux 3, the selected EPEL unit is `certbot-renew.timer`; another
safe timer is accepted only when explicitly configured and evidence-bound. The
runtime-data encryption cutover does not create or repair that topology. Do
not edit the active env. After the topology succeeds, prepare the separate
exact-five-key Edge-readiness input; P1-E06's first lock-held preflight
publishes those keys and re-verifies certificate readiness before any image or
database mutation.
The timer's effective `Unit` must resolve to one service whose effective
`ExecStart` directly invokes the canonical, root-owned,
non-group/world-writable Certbot executable with the `renew` subcommand. Shell
or `env` wrappers, no-op services, ignored errors, dry-run-only commands,
hook-disabling flags, and unrelated Certbot subcommands fail closed.
NGINX must reference the Certbot live-lineage `fullchain.pem` and `privkey.pem`
paths directly; copied certificate files are forbidden because renewal would
not update the active Edge. Each live path must be a symlink whose final,
root-owned non-symlink target is in the matching `/etc/letsencrypt/archive`
lineage, and the private-key target grants no group or other permissions. The
readiness receipt parses `nginx -T`, binds both directives and their digest,
and proves the certificate/private-key pair matches before checking the served
leaf.
Pure `--stage-only` archive upload/verification may run while the gate is
pending,
but do not start `runtime-data-encryption-cutover.sh` or mutate images until it
is complete.

Once host NGINX is active, generate the machine-verifiable gate from the exact
staged release:

```bash
sudo NPCINK_CLOUD_RELEASE_TOOL_PYTHON=/usr/bin/python3.11 \
  "${STAGED_RELEASE}/deploy/certificate-renewal-readiness.sh" generate \
  --domain cloud.npc.ink \
  --certificate-path /etc/letsencrypt/live/cloud.npc.ink/fullchain.pem \
  --owner certbot \
  --timer certbot-renew.timer \
  --deploy-hook-path /etc/letsencrypt/renewal-hooks/deploy/reload-nginx \
  --evidence-path /var/lib/npcink-ai-cloud/edge/certificate-renewal-readiness.json
```

The root-owned mode-`0600` evidence binds `renewal_service`,
`certbot_real_path`, `renewal_exec_start_sha256`, both Certbot archive targets,
the derived `privkey.pem`, and the actual NGINX TLS binding; `verify` resolves
and compares them again. It is fresh for at most seven days.
Place all four explicit values in the protected exact-five-key Edge-readiness
input shown below; P1-E06 alone persists them with the readiness flag into the
active env:

```dotenv
NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH=/etc/letsencrypt/live/cloud.npc.ink/fullchain.pem
NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH=/var/lib/npcink-ai-cloud/edge/certificate-renewal-readiness.json
NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER=certbot-renew.timer
NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH=/etc/letsencrypt/renewal-hooks/deploy/reload-nginx
```

Formal runtime has no defaults for these values. `generate` atomically removes
and fsyncs any prior success before it starts live checks, so a failed rerun
cannot leave old evidence usable. The explicit `prepare-only` image phase and
P1-E06 verify this receipt before image mutation. Regenerate it after
certificate or hook rotation; do not edit or copy a stale receipt into place.

Inventory note (2026-07-20): host NGINX was absent, the retired Caddy was still
running, and the readiness flag was absent. This is a dated operator snapshot,
not a permanent release-policy condition.

### Historical first migration to the external Edge (non-normative)

Before the first deploy of this topology:

1. Retain the previous exact bundle and matched database recovery point. Keep
   the retired Caddy container running while the host Edge is prepared.
   Provision the certificate and preinstall host NGINX, EPEL Certbot, and
   `curl`, but do not enable renewal or mutate images yet.
2. Run the binding helper in read-only preparation mode. Certificate paths are
   remote Certbot paths; no TLS material is uploaded:

   ```bash
   bash deploy/bind-domain-to-ssh-host.sh \
     --ssh-host "${SSH_HOST}" \
     --ssh-user root \
     --domain cloud.npc.ink \
     --certificate-path /etc/letsencrypt/live/cloud.npc.ink/fullchain.pem \
     --private-key-path /etc/letsencrypt/live/cloud.npc.ink/privkey.pem \
     --prepare-only
   ```

   It holds the shared `/opt/npcink-ai-cloud/.deploy-lock`, validates the
   Certbot lineage, target ownership/modes, certificate/key match, inner
   ingress, and candidate `nginx -t`, then restores the exact prior NGINX files.
   It does not stop Caddy, restart NGINX, switch traffic, or leave a prepared
   config that could overwrite unique rollback evidence.
3. Rerun the same command without `--prepare-only`. Do not stop Caddy manually.
   One locked remote transaction freezes the prior NGINX files/service state
   and exact running Caddy IDs, installs the direct Certbot-lineage config,
   stops only those IDs, activates NGINX, and proves HTTPS through loopback. On
   any failure it restores NGINX, restarts and verifies those exact original
   Caddy IDs, and returns nonzero. If rollback proof fails, it preserves the
   rollback directory and shared lock for manual recovery. After final health,
   it marks the new Edge committed while still locked and only then releases
   the lock; release failure preserves the healthy Edge, lock, and evidence,
   returns nonzero, and never starts a post-commit rollback. Only after success
   may the separate P1-E06 Edge-readiness input declare
   `NPCINK_CLOUD_EXTERNAL_EDGE_READY=true`; do not edit the active env.
4. Install the persistent host hook, then enable and inspect the EPEL timer:

   ```bash
   sudo install -d -o root -g root -m 0755 /etc/letsencrypt/renewal-hooks/deploy
   printf '%s\n' '#!/usr/bin/env bash' 'set -Eeuo pipefail' \
     '/usr/sbin/nginx -t' '/usr/bin/systemctl reload nginx' | \
     sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx >/dev/null
   sudo chown root:root /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
   sudo chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
   sudo systemctl enable --now certbot-renew.timer
   sudo systemctl show certbot-renew.timer \
     --property=NextElapseUSecRealtime --value
   sudo /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
   ```

5. Generate the certificate-renewal evidence shown above and persist all four
   readiness env values. There is no current real receipt, so production is
   blocked here until `generate` and then `verify` pass.
6. Only then run the normal release loader. Confirm it reports
   `[ok] Retired bundle services are absent: caddy jaeger otel-collector` before
   public health verification.
7. Verify forwarded-header replacement, HTTPS, operational readiness, signed
   runtime execution, media upload
   and pull behavior, and external trace export/query evidence.

The loader uses orphan removal and then rejects a release project that still
contains a `caddy`, `jaeger`, or `otel-collector` container. Do not manually
rename a retired container to bypass this check.

If activation fails before the loader runs, the same binding transaction
restores host NGINX and restarts/verifies its frozen Caddy IDs. Do not perform a
second manual ingress switch. If the loader fails before migration and its
rollback evidence is complete, it may restore the matched previous application.
Once migration starts, it deliberately leaves application/write services
stopped and restores only the prior pointer; an operator must decide whether to
restore the matched previous bundle, external env state, database recovery
point, and Caddy route. Restore only one public ingress chain; do not start
Caddy beside host NGINX or attach retired observability containers to the
current release project.

## First Installation

A host with missing or `pending` installation state takes the bounded first-
install path. Before remote mkdir, upload, deployment lock, image, container, or
database mutation, the deploy helper reads the protected state with
`/usr/bin/python3.11`. While its canonical CVE allowlist contains the exact
three governed Python 3.14.6 exceptions, it accepts only a fresh external
`npcink.controlled_production_cve_risk_acceptance.v1` receipt plus its separate
SHA-256 file. Both must be operator-owned mode `0600` and bind the exact
Linux/AMD64 source, bundle, embedded allowlist, passed scan index, API receipt,
finding set, current `exploitation:none` check, operator, and expiry. There is
no generic skip. A missing or mismatched pair fails before upload or mutation.

This temporary first-install path may be run from the trusted operator
workstation only after the exact `production` commit is CI-green and the
production-promotion PR records the standard approval sentence. It exists
because the acceptance is created after and binds the final local exact bundle.
It expires no later than 2026-08-05, authorizes no GA or real-user rollout, and
cannot be used for ordinary deployments after the completion sentinel exists.
See the risk decision and PostgreSQL 18 runbook for the two explicit evidence
environment variables.

The first deployment starts Redis, the setup-capable API, frontend, and proxy,
then emits exactly `installation_state=pending`. The workflow skips ordinary
post-install smoke and directs the root operator to rotate/display the setup
code in a TTY, open `/setup`, configure the external RDS PostgreSQL 18
connection and CA, and capture the one-time administrator key. The browser UI
uses `/setup`; `/setup/v1/` remains the API namespace.

After independent release smoke, WordPress text/image round trips, RDS restore,
and the 24–72 hour observation pass, run `deploy/first-install-finalize.sh` from
the active direct managed release. Finalization publishes the permanent
root-owned mode-`0600` `.installation-complete` sentinel. Every ordinary deploy
and mutating `safe-prune` requires that positive sentinel plus current protected
`complete`, `pg18_empty_initialization.v1`, and runtime-config digest evidence.
Deleting a pending marker or losing database connectivity never reopens setup.

## Promotion Flow

```text
local feature work
  -> PR to master
  -> Cloud CI passes
  -> PR master -> production
  -> Cloud CI passes on production
  -> operator enters the exact production-validation approval phrase
  -> ordinary deploy: manually dispatch Deploy Production in the production Environment
     OR temporary first install: exact-receipt trusted-workstation deploy
  -> operational-ready passes
```

The remote cutover order is fixed:

```text
validate complete-state and protected runtime-config digest
  -> prepare images
  -> candidate-image RDS PostgreSQL 18/TLS/Alembic preflight
  -> stop old application/write services
  -> Redis
  -> external RDS migration and provider refresh
  -> current pointer
  -> API readiness
  -> workers plus cutoff/container/heartbeat stability
  -> generic operational-ready
  -> frontend/proxy traffic
```

Before `prepare images`, both release env files must resolve the same Compose
project name. Ordinary production deployment also requires an existing managed
`current` release; it is not a host-bootstrap path. Before image mutation it
proves `complete`, `database_contract=pg18_empty_initialization.v1`, and the
exact protected runtime-config digest. After exact images load and before old
writers stop, the candidate API proves private RDS resolution, TLS
`verify-full`, PostgreSQL major 18, and one known Alembic revision that is the
candidate head or its ancestor. After migration the exact sole candidate head
is required. The retired
PG16/P1-E06 receipt is not an ordinary deployment input. Migration and provider
refresh use the profiled `release-one-off` API service, pinned to the recorded
target-local daemon ID. Compose creates exactly one stopped candidate with
`up --no-start --pull never --no-build --no-deps --force-recreate`. Post-load
verification first proves the loaded
image's portable Config image ID and platform against the exact bundle, then
records the corresponding target-local daemon ID only in
.release-state/<release-name>/target-daemon-images.json`. The one-off compares
the stopped candidate's `.Image` and current tag with this recorded target-local
ID, starts only the captured container ID, rechecks that same running identity,
then executes the payload through `docker exec -i` and removes the container.
One fixed private lock under the managed `.release-state` root serializes
one-offs across releases. Signal cleanup is mandatory; incomplete container or
protected-stdin cleanup retains that lock for operator recovery. Runtime
Compose also uses `pull_policy: never`. Once migration begins, a
failure is fail-closed: old application services are not automatically
started against the changed or partially changed schema. Recovery must prove
that all public/write services are stopped, `current` is restored, and a
restricted failure marker exists. If any recovery proof is incomplete,
`.deploy-lock` is retained for an operator. A successful deploy retains
`.release-state/<release-name>/env.deploy`, removes the temporary rollback-image map,
and removes private rollback tags.
After the new runtime has passed activation checks, failure to clean protected
incoming state, rollback tags, the rollback map, stale failure evidence, or the
deploy lock keeps the healthy new `current` but fails the deployment. The
remote transaction writes `outcome=post_commit_cleanup_incomplete`, retains the
map and lock, and never starts the previous runtime. Success is emitted only
after cleanup and unlock are proved.

The loader has no default or aggregate phase; the orchestrator must select one
of `prepare-only`, `data-only`, `api-only`, `workers-only`, or `traffic-only`.
For every service-start phase it freezes all required daemon IDs from the fixed
map, pins Compose to those IDs, and creates force-recreated stopped candidates
with `up --no-start --pull never --no-build --no-deps --force-recreate`. It
captures exactly one container ID per service, verifies every candidate's
`.Image`, and re-proves the complete phase's governed tags against the map. Only
then does it run
`docker start` with those captured IDs; the same IDs and images must pass the
post-start identity and running-state checks before health or readiness.

If the global `.release-state/.release-one-off.lock` remains, stop automation
and treat it as recovery evidence. Never remove the lock first. If
`.deploy-lock` also exists, resolve that deployment's failure marker before
touching either lock. Otherwise query all projects with
`docker container ls -a --no-trunc --filter
"label=com.docker.compose.service=release-one-off"`, remove only the captured
full IDs, and repeat both the label query and exact-ID queries until absence is
proved. Check for a root-owned private `npcink-release-proof-stdin.*` directory
under the configured temporary root and remove it only after its container is
absent. Only then verify the lock is a root-owned, non-symlink, empty mode-0700
directory and remove it with `rmdir`; any ambiguous query or filesystem state
keeps the lock and escalates to manual recovery.

Runtime configuration changes are releases. Never edit the active release's
external `.release-state/<release-name>/env.deploy`, protected
`shared/config/`, or directly restart its Compose services. Apply non-secret
host/runtime-tuning changes through `deploy/deploy-to-ssh-host.sh`; database and
runtime-root changes require their dedicated governed procedure. The same
deploy lock, exact bundle/image proof, rollback point, and readiness gates own
the change. The ordinary governed path still does not apply to either
encryption pair:
`NPCINK_CLOUD_SERVICE_SETTINGS_SECRET` /
`NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID` or
`NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET` /
`NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID`. Never rotate them through the
ordinary deploy path because existing ciphertext must be re-encrypted while
all four writers are stopped. Code, policy, billing, governance, and provider
routing logic changes must go through Git.

The retired first P1-E06 operation had one narrow exception implemented only inside
its orchestrator: while `.deploy-lock` is held, it may atomically add the exact
five non-secret Edge-readiness keys from a separate protected file. It first
freezes the original env bytes and digest, records value-free handoff evidence,
restores the original bytes on pre-migration failure, and retains that snapshot
for whole recovery after migration begins. This is not a general active-env
update mechanism and does not authorize direct editing.

## Historical One-Time P1-E06 Dual-Domain Encryption Maintenance (non-normative)

This preserved PostgreSQL 16 procedure is an audit record only. It is not a
current promotion gate, activation-receipt requirement, or supported
compatibility path after the fresh PostgreSQL 18 initialization.

This maintenance path is deliberately separate from the normal deployment
sequence above. The first Runtime Data and Service Settings raw-ciphertext
migrations use one governed entry point and one writer fence/backup/restore
window; operators must not assemble a second sequence from lower-level helpers.
Each target root is canonical padded URL-safe Base64 that decodes to exactly 32
random bytes. The two domains have separate target roots and separate key IDs.

1. From the trusted workstation, run
   `deploy/deploy-to-ssh-host.sh --stage-only --skip-bundle-build` against the
   already verified Linux/AMD64 bundle. Stage-only must not receive
   `--env-file` or `NPCINK_CLOUD_ENV_FILE`. Select
   `/usr/bin/python3.11` with `--host-python` (or
   `NPCINK_CLOUD_DEPLOY_HOST_PYTHON`) and accept only its
   `staged_release=/absolute/release-path` result. It uploads, archive-checks,
   safely extracts, and pre-load verifies the bundle; it does not resolve or
   change `current`, create `.release-state`, call Docker, load images, mutate
   containers, migrate, refresh, seed, smoke, or start traffic. Its remote
   argument envelope contains only stage mode, managed root, release/incoming
   paths, and host Python. The Python `>=3.11` check occurs before remote mkdir,
   upload, or lock; any later failure removes the incoming object, partial
   release, and stage lock.
2. Recheck and close the independent production Edge hard gate. Stage-only may
   have completed already, but no image mutation or cutover command may begin
   while that gate is pending. Normalize `/opt/npcink-ai-cloud` to `root:root`,
   prove no managed path is group/world-writable, and create root-owned mode
   `0700` `/var/backups/npcink-ai-cloud` and `/run/npcink-ai-cloud`.
3. Create `/run/npcink-ai-cloud/p1-e06-edge-readiness.env` outside the managed
   release tree as a root-owned, non-symlink, mode-`0600` file containing
   exactly:

```text
NPCINK_CLOUD_EXTERNAL_EDGE_READY=true
NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH=/etc/letsencrypt/live/cloud.npc.ink/fullchain.pem
NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH=/var/lib/npcink-ai-cloud/edge/certificate-renewal-readiness.json
NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER=certbot-renew.timer
NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH=/etc/letsencrypt/renewal-hooks/deploy/reload-nginx
```

   The orchestrator is the only process allowed to merge these keys into the
   current env. It snapshots the original bytes as `.current-env.snapshot`,
   proves that no other key changed, fsyncs the lock owner and recovery
   directory chain before replacement, and writes value-free
   `p1_e06_edge_readiness_env_handoff.v1` evidence. Handled pre-migration
   failures and catchable `HUP`/`INT`/`TERM` signals restore those exact bytes;
   an uncatchable `SIGKILL` or host power loss leaves the persistent snapshot
   and deploy lock for manual recovery.
4. Create the mode-`0600` maintenance env outside the managed release tree. It
   contains exactly six keys:

```text
NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET=<canonical-base64-32-byte-target-root>
NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID=<target-key-id>
NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET=<old-runtime-root>
NPCINK_CLOUD_SERVICE_SETTINGS_SECRET=<canonical-base64-32-byte-target-root>
NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID=<target-key-id>
NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET=<old-service-settings-root>
```

The two old-root variables are available only to the matching `dry-run` and
`apply`; neither `inventory`, new-key-only `verify`, nor normal runtime receives
them. The orchestrator freezes this exact six-key source under `.deploy-lock`.
A post-migration/pre-activation failure retains `.maintenance-env.snapshot`
and records its SHA-256 in `.cutover-failed`; naming the variables without the
bound snapshot is not recovery evidence. Pre-migration failure and successful
activation remove the frozen private copy.

5. Run `deploy/runtime-data-encryption-cutover.sh` once, in the foreground,
   with the staged path, Edge-readiness env, maintenance env, fresh host backup
   path, previously absent receipt path, optional receipt timeout, and all
   three explicit acknowledgements. The command owns governed `remote-load-and-up.sh`
   `prepare-only` image loading, writer/public fencing, backup, independent
   restore, migration, re-encryption, pointer, readiness, traffic restoration,
   evidence, cleanup, and unlock:

```bash
sudo "${STAGED_RELEASE}/deploy/runtime-data-encryption-cutover.sh" \
  --remote-dir /opt/npcink-ai-cloud \
  --staged-release "${STAGED_RELEASE}" \
  --host-python /usr/bin/python3.11 \
  --edge-readiness-env /run/npcink-ai-cloud/p1-e06-edge-readiness.env \
  --maintenance-env /run/npcink-ai-cloud/runtime-data-reencrypt.env \
  --backup-path /var/backups/npcink-ai-cloud/p1-e06.dump \
  --off-host-receipt /run/npcink-ai-cloud/p1-e06-off-host-receipt.json \
  --off-host-receipt-timeout-seconds 900 \
  --confirm-off-host-handoff I_ACKNOWLEDGE_THE_BACKUP_COPY_IS_OFF_HOST_AND_INDEPENDENT \
  --confirm-whole-database-restore I_ACKNOWLEDGE_ROLLBACK_RESTORES_DATABASE_RELEASE_ENV_AND_BOTH_OLD_ROOTS_TOGETHER \
  --confirm-production-cutover I_AUTHORIZE_THE_P1_E06_PRODUCTION_CUTOVER
```

6. After the fresh custom-format backup and checksum are atomically published,
   the same process writes a mode-`0600` handoff marker and waits. The operator
   pulls both files with `scp` to independent off-host storage, verifies the
   checksum locally, creates a mode-`0600`
   `p1_e06_off_host_backup_receipt.v1` JSON receipt with the matching SHA, and
   uploads it to a temporary sibling before atomically renaming it to the exact
   path printed by the script. A same-host copy or pre-created receipt is not
   proof. The script persists the validated receipt as
   `off-host-receipt-verified.json`, including its source path and SHA-256, and
   includes that digest in terminal evidence.
7. Only after that receipt does the script perform an independent PostgreSQL 16
   restore and `0058 -> 0068`, then separately runs
   `inventory -> dry-run -> apply -> verify` through
   `python -m app.dev.reencrypt_runtime_data` and
   `python -m app.dev.reencrypt_service_secrets`. Both the restored rehearsal
   and production are count-locked to 18 Runtime Data rows (17 site signing
   secrets plus one Addon connection payload), 12 service-secret ciphertexts
   (eight provider connections plus four service-setting secret entries), and
   30 ciphertexts total. Each `apply` is an independent database transaction; both applies and
   both verifies must pass. It then switches production PostgreSQL and Redis to
   the exact target image IDs and proves both are healthy plus PostgreSQL is
   still at `0058` before migration. Every API one-off uses the governed
   `release-one-off` stopped candidate: Compose creates it with `up --no-start
   --pull never --no-build --no-deps --force-recreate`, the host proves its
   exact image and never-started state, starts the captured ID, then passes only
   variable names through `docker exec -i --env VARIABLE_NAME`. Secret value
   arguments and env-file run options are forbidden. Runtime Compose
   `pull_policy: never` and exact API image-ID proof are required. Inventory and
   new-key-only `verify` receive no old-root variable; only each matching
   `dry-run` and `apply` do. The first raw-ciphertext cutover omits
   `--old-key-id`. Production repeats both four-phase sequences inside the same
   stopped-writer and backup/restore window.
   The script additionally freezes the sorted row-identifier sets using
   canonical-JSON SHA-256 (`675cce444dbbf801bc8ab7fb35b717888c878e062097e5fb7f2f5f110e5a764c`
   for Runtime Data and
   `e5010d2b0a2afe22b7729c4c2395c91001a078e282abee87f03a5f0289aa0bf6`
   for Service Settings), so a count-preserving identity substitution cannot
   pass. Any intentional inventory change requires a stopped, reviewed digest
   update before cutover.
8. After restoring traffic and validating the active release, the script
   durably publishes `activation-commit.json`. This is the irreversible
   activation commit point. It then cleans rollback tags/maps, publishes the
   authoritative mode-`0600`
   `.release-state/<staged-release-name>/p1-e06-runtime-data-cutover/cutover-result.json`,
   publishes the global activation receipt bound to the activation-commit and
   cutover-result digests, and only then releases `.deploy-lock` and marks the
   command complete. A command that has not reached all of those states is
   terminalization incomplete, not necessarily a runtime rollback.

Before production migration starts, recovery may resume the unchanged `0058`
database with the old release and both old roots after pointer, schema, and
dependency health are proven. If PostgreSQL/Redis had already switched to target image IDs,
restore their recorded prior tags and recreate/prove those dependencies before
starting the old application; otherwise prove the existing dependencies and
then restore the old application. Once production migration starts and before
activation commits, never downgrade or restart old code: restore the whole
fresh `0058` dump, old application revision, the original external env from
the retained `.current-env.snapshot`, and both old roots from the digest-bound
`.maintenance-env.snapshot` together. Runtime Data and Service Settings
`apply` are independent
transactions, but failure of either or any later pre-activation step requires
that full recovery point; keeping only one newly encrypted domain is forbidden.
Migration `0061` removes legacy media/audio tables, so downgrade cannot
reconstruct their old bytes.

After `activation-commit.json` exists, cleanup, private/global evidence, or
unlock failure must keep the healthy new runtime and pointer. Do not stop writers,
restore tags, or launch destructive rollback. Retain or reacquire `.deploy-lock`
and write `.cutover-failed` with
`outcome=activation_committed_terminalization_incomplete` plus
`recovery=do_not_rollback_healthy_active_runtime`, then repair terminalization.

Future `rde.v1` to `rde.v1` rotation remains a separate, manually approved
maintenance procedure; it is not an alternate P1-E06 entry point. No direct
Compose command is approved. Implement and review a dedicated orchestrator
that reuses the deployment-owner/global-one-off handshake, exact stopped
candidate image proof, names-only protected environment handoff, cleanup
proof, and the same backup, receipt, fence, restore, and rollback gates.
Inventory and new-key-only `verify` must still omit every old root.

Normal runtime has no legacy or dual-read path. It accepts only active `rde.v1`
and `sse.v1` envelopes and rejects raw Fernet. The Runtime Data tool supports
the separately approved future `rde.v1` rotation described in
`deploy/OPS_PLAYBOOK.md`; the Service Settings tool supports only the first
raw-Fernet to `sse.v1` cutover and must be extended under a new approved
contract before any future `sse.v1` rotation. Both commands remain
migration-only offline maintenance tools, never normal runtime fallbacks.
