# Cloud Ops Playbook

> Status: active
>
> Updated: 2026-07-20
>
> Scope: standalone `npcink-ai-cloud` production operations, cadence recovery, signed runtime smoke, release-time troubleshooting

## Purpose

This playbook is the minimum operator contract for Npcink AI Cloud production work.
If a release depends on manual knowledge that is not written here, the release is not closed.

Primary internal checkpoints:

- `GET /health/live`
- `GET /health/ready`
- `GET /health/operational-ready`
- `GET /internal/service/observability/summary`
- `GET /internal/service/ops/cadence`
- `GET /internal/service/runtime/diagnostics/summary`
- `GET /internal/service/runtime/diagnostics/backlog`
- signed `GET /v1/catalog/models`
- signed `POST /v1/runtime/execute`
- signed `GET /v1/runs/{run_id}`
- signed `GET /v1/runs/{run_id}/result`
- signed `GET /v1/stats/profiles/{profile_id}`
- signed `GET /v1/usage/summary`

## Environment Entry Points

Cloud has two operator-known public entry points in the current deployment
model:

- local development: `http://127.0.0.1:8010/`
- production: `https://cloud.npc.ink/`

Configuration ownership:

- local compose may use the loopback origin for development and smoke testing.
- production must set `NPCINK_CLOUD_BASE_URL=https://cloud.npc.ink` in the
  protected per-release env state or the deploy secret store.
- production Runtime Compose must set `NPCINK_CLOUD_EXTERNAL_EDGE_READY=true`
  and `NPCINK_CLOUD_DOMAIN_NAME=cloud.npc.ink`. The base URL must use HTTPS and
  its host must exactly match `NPCINK_CLOUD_DOMAIN_NAME`.
- production must set
  `NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST=https://cloud.npc.ink` and
  `NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST=cloud.npc.ink`.
- production must keep both
  `NPCINK_CLOUD_SERVICE_SETTINGS_SECRET` /
  `NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID` and
  `NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET` /
  `NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID` stable across ordinary deploys.
  Both pairs belong to all four backend writers; the frontend receives none of
  the four variables.
- `/admin/service-settings` owns Portal public URL, QQ login, and SMTP sender
  settings. Do not move those service settings back into `.env`.

Managed production releases keep code and secret state separate:

```text
code:  /opt/npcink-ai-cloud/release-*/
state: /opt/npcink-ai-cloud/.release-state/<release-name>/env.deploy
image identity:
       /opt/npcink-ai-cloud/.release-state/<release-name>/target-daemon-images.json
```

The release payload never contains `.env.deploy`. Both `.release-state` and its
release child must be owner-controlled non-symlink directories with mode
`0700`; `env.deploy` and `target-daemon-images.json` must be owner-controlled
regular files with mode `0600`. The target-daemon map path is derived only from
the managed release basename and cannot be redirected by an environment
variable or CLI option. The `current` symlink selects a code directory whose
basename selects its matching
external state. Do not copy production env state into `current` or any release
payload.

Loopback origins are a development convenience only. If a production frontend
requires `http://127.0.0.1:8010` or `localhost` as a public URL, treat that as a
release-blocking environment configuration error.

### Production host ownership and release-tool Python

Production release tooling and Cloud application code have separate Python
contracts:

- release tooling on the host uses
  `NPCINK_CLOUD_RELEASE_TOOL_PYTHON=/usr/bin/python3.11` and requires Python
  `>=3.11`;
- the Cloud application runs only inside the exact release image and requires
  Python `>=3.12`; host Python must never be treated as an application runtime.

Set `NPCINK_CLOUD_DEPLOY_HOST_PYTHON=/usr/bin/python3.11`, or pass
`--host-python /usr/bin/python3.11`, for the production SSH deploy. The deploy
entry point verifies the absolute executable and its version over SSH before it
creates a remote incoming directory, uploads bytes, or acquires `.deploy-lock`.
Install or repair that host prerequisite before retrying; do not upload a
bundle first and hope a later remote phase can recover.

All managed production paths under `/opt/npcink-ai-cloud` are root-owned. Before
the P1-E06 cutover, normalize the managed tree to `root:root` and prove that no
managed directory or file is group- or world-writable. Create the transient and
backup roots explicitly:

```bash
sudo chown -R root:root -- /opt/npcink-ai-cloud
test -z "$(sudo find /opt/npcink-ai-cloud \( ! -user root -o ! -group root -o -perm /022 \) -print -quit)"
sudo install -d -o root -g root -m 0700 \
  /var/backups/npcink-ai-cloud \
  /run/npcink-ai-cloud
```

Run the cutover as root. Do not mix a deploy-user-owned release tree with a
root-owned lock, state, backup, or evidence tree.

### External Edge and bundled NGINX

Production has one public chain:

```text
client -> operator-owned TLS Edge -> 127.0.0.1:8010 bundled NGINX -> Gunicorn
```

The external Edge owns public `80/443`, certificates, TLS policy, DNS, and any
WAF/source restriction. It must replace client-supplied `X-Real-IP`,
`X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host`, and
`X-Forwarded-Port` values. The bundled NGINX trusts client-address evidence
only from the Compose gateway `172.28.0.1` and sets the upstream
`X-Forwarded-For` to `$remote_addr`; Gunicorn trusts forwarded headers only
from NGINX at `172.28.0.10`.

The exact-bundle smoke may replay the artifact through loopback NGINX over
plain HTTP. That is a local verification exception, never a production public
origin.

P1-E06 has an independent production Edge hard gate. Before invoking the
cutover, install and activate host NGINX through the governed binding helper,
pass `nginx -t` and the exact-host loopback-resolved HTTPS check, stop the
retired project Caddy, and complete the certificate-readiness evidence below.
Do not edit the active env. Prepare the separate exact-five-key Edge-readiness
input only after that topology succeeds; P1-E06's first lock-held preflight
publishes those keys and re-verifies the evidence before any image or database
mutation. The encryption cutover neither creates nor repairs the Edge topology.
Pure `--stage-only` upload and verification may run while this gate is pending
because it does not inspect runtime state or mutate images.

The gate also requires a named certificate-renewal owner, an enabled automatic
renewal service/timer, a persistent root-owned non-writable executable hook in
`renewal-hooks/deploy`, a successful renewal dry run, direct hook/reload proof,
and at least 30 days remaining on both the named PEM leaf and the leaf actually
served by `127.0.0.1:443`. Their SHA256 fingerprints must match. On the current
Alibaba Cloud Linux 3 target, use the EPEL `certbot-renew.timer`; another timer
is accepted only when explicitly selected and bound into evidence. Do not
retire Caddy while it is still the only working certificate-renewal owner.
The selected timer must resolve through its effective `Unit` to one service
whose effective `ExecStart` directly invokes the canonical, root-owned,
non-group/world-writable Certbot executable with a real `renew` subcommand.
Shell or `env` wrappers, no-op services, ignored errors, dry-run-only commands,
hook-disabling flags, and unrelated Certbot subcommands are release-blocking
failures.
Host NGINX must reference the Certbot live-lineage `fullchain.pem` and
`privkey.pem` directly. Do not copy either file into `/etc/nginx/ssl`: renewal
would rotate the lineage target while NGINX kept serving the stale copy. Both
live paths must be symlinks to root-owned, non-symlink files in the matching
`/etc/letsencrypt/archive` lineage; the private-key target must grant no group
or other permissions. Readiness parses the effective `nginx -T` server block,
binds both directives and their digest, proves keypair equality, then compares
the named and loopback-served leaves.

After host NGINX is active, generate the fail-closed evidence from the exact
staged release. The script is root-only, requires `/usr/bin/python3.11`, runs a
real Certbot dry run followed by a direct persistent deploy-hook/reload test,
and atomically writes a root-owned
mode-`0600` receipt. The receipt binds `renewal_service`, `certbot_real_path`,
`renewal_exec_start_sha256`, both archive targets, the derived private-key
path, and the actual NGINX TLS binding; `verify` resolves and compares them
again. The receipt is valid for at most seven days:

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

Place all four exact values in the protected exact-five-key Edge-readiness
input shown in the P1-E06 procedure; P1-E06 alone persists them with the
readiness flag into the active env. Formal runtime has no fallback for any of
them:

```dotenv
NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH=/etc/letsencrypt/live/cloud.npc.ink/fullchain.pem
NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH=/var/lib/npcink-ai-cloud/edge/certificate-renewal-readiness.json
NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER=certbot-renew.timer
NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH=/etc/letsencrypt/renewal-hooks/deploy/reload-nginx
```

The explicit `prepare-only` image phase and P1-E06 itself run `verify` before
image snapshot/tag/load or database work. `generate` first removes and
fsyncs any prior receipt, so a failed regeneration leaves no reusable success.
Regenerate after certificate or hook rotation and before the receipt becomes
seven days old; never hand-edit the JSON.

Inventory note (2026-07-20): host NGINX was absent, the retired Caddy was still
running, and the external-Edge readiness flag was absent. This dated note is
operator context, not a permanent policy assertion; update it after the gate is
closed without weakening the stable checks above.

For the first migration from the retired bundled edge:

1. Retain the previous bundle and matched database recovery point while the old
   Caddy route remains active. Provision the certificate, preinstall host NGINX,
   EPEL Certbot, and `curl`, but do not yet enable renewal or mutate images.
2. Run `deploy/bind-domain-to-ssh-host.sh --prepare-only` with the remote
   `/etc/letsencrypt/live/<lineage>/fullchain.pem` and matching `privkey.pem`
   paths. The helper must hold `/opt/npcink-ai-cloud/.deploy-lock`, validate the
   lineage/targets, keypair, loopback upstream and candidate `nginx -t`, then
   restore the exact prior NGINX files. This mode must not upload TLS material,
   stop Caddy, restart NGINX, switch traffic, or leave a prepared config behind.
3. Rerun the same binding command without `--prepare-only`; do not manually stop
   Caddy between invocations. The one locked remote transaction freezes NGINX
   state plus exact running project-Caddy IDs, stops only those IDs, activates
   and validates NGINX, and commits only after loopback-resolved HTTPS succeeds.
   Any failure restores NGINX and restarts/verifies the exact frozen Caddy IDs.
   Incomplete rollback preserves its evidence and `.deploy-lock` for recovery.
   Final health is marked committed while the lock is still held; if lock
   release then fails, retain the healthy Edge plus lock/evidence, return
   nonzero, and do not perform a post-commit rollback.
4. Install the persistent hook and enable the Alibaba Cloud Linux 3 EPEL timer:

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

   This persistent operator-owned hook is host Edge configuration, not Cloud
   application code. Directly run the installed hook once and require success;
   the readiness receipt binds its absolute path and SHA256.
5. Run `certificate-renewal-readiness.sh generate` exactly as above, persist all
   four certificate-readiness env values, and leave image preparation blocked
   unless `verify` succeeds. No current production receipt exists, so this gate
   remains open today.
6. Only then run the normal release loader and require its marker
   `[ok] Retired bundle services are absent: caddy jaeger otel-collector`
   before public health verification.
7. Confirm no current Compose-project container is named for `caddy`, `jaeger`,
   or `otel-collector`, then verify public HTTPS, operational readiness, signed
   runtime, and media upload/download controls.

The binding helper itself restores prior host NGINX files/service state and
restarts/verifies only its frozen Caddy IDs when activation fails. Do not
perform a second manual ingress switch. After the loader starts, rollback is
`stop the new project -> stop host NGINX -> restore the matched prior bundle
and database recovery point when required`. The loader uses Compose orphan
removal and fails closed on any residual retired service. Never leave both
Caddy and host NGINX active, and never attach retired observability containers
to the current release project.

### Atomic release cutover

Before any mutation, resolve the previous release env and the new release env
from their external `.release-state/<release-name>/env.deploy` files. Both must
produce the same Compose project name, and each running old writer's actual
Compose project label must match it. A project rename or label drift during an
ordinary deploy is a blocking configuration error because it can leave old
writers outside the stop/recovery set. `--skip-frontend-image` is valid only
when exactly one running old frontend exists to preserve; never use it for a
first deploy or a missing frontend. Ordinary production deployment also
requires an existing managed `current` release and must not bootstrap a new
host. Before
image loading it queries PostgreSQL through the frozen previous release;
revision `20260710_0058` is a hard stop requiring the P1-E06 orchestrator.
The protected env file remains the complete Compose/backend runtime input.
Root-owned host helpers import only their explicit reviewed key allowlist;
unlisted `NPCINK_CLOUD_*`, database, provider, and PostgreSQL values stay in
the file for Compose and do not become shell controls.
Formal production dispatch additionally verifies the persistent global
activation receipt, its complete digest-bound cutover evidence, and that the
current revision is `0068` or a descendant in the staged Alembic graph. The
ordinary production deployment requires that receipt gate and cannot disable
it; the production workspace target also exports
`NPCINK_CLOUD_REQUIRE_P1_E06_RECEIPT=1`. Only
`--stage-only` omits the receipt.

The normal deploy sequence is fixed:

```text
prepare exact images
  -> stop old public and write-capable services
  -> start/retain PostgreSQL and Redis
  -> migrate and refresh providers with staged one-off API containers
  -> atomically update current
  -> start and verify API
  -> start workers
  -> prove worker cutoff, container identity/restart stability, and post-cutoff heartbeats
  -> pass generic operational-ready
  -> restore frontend/proxy traffic
```

Migration and provider refresh use the profiled `release-one-off` API service.
Compose pins it to the recorded target-local daemon ID and creates it with
`up --no-start --pull never --no-build --no-deps --force-recreate`. Post-load
verification first proves the loaded
image's portable Config image ID and platform against the exact bundle, then
records the corresponding target-local daemon ID only in the fixed
`.release-state/<release-name>/target-daemon-images.json` map. Release tooling
requires exactly one stopped candidate, compares both its `.Image` and the tag
with this recorded target-local ID, and only then starts the captured container
ID. It rechecks the running identity before executing the payload through
`docker exec -i` on that same ID, then removes the proof container. Its inert
process waits until exact cleanup terminates it. A fixed private lock under the
managed `.release-state` root serializes one-offs across releases; incomplete
container or protected-stdin cleanup retains that lock for operator recovery.
Runtime Compose also sets `pull_policy: never`.

`remote-load-and-up.sh` has no default or aggregate phase. Its only accepted
values are `prepare-only`, `data-only`, `api-only`, `workers-only`, and
`traffic-only`; `prepare-only` starts nothing. Every service-start phase freezes
all required daemon IDs from the fixed map, pins Compose to those IDs, and uses
`up --no-start --pull never --no-build --no-deps --force-recreate` to create a
complete stopped candidate set. The loader captures exactly one container ID
per service, verifies every candidate `.Image`, and re-proves every role/tag in
the whole phase against the map. Only then does it call `docker start` with the
captured IDs. It must verify those same IDs are running with those same image
IDs before the phase's health or readiness check can pass.
The worker gate requires exactly one `worker`, `callback-worker`, and
`ops-worker` container, all running and non-restarting with zero restarts and a
stable container ID, plus `runtime_queue`, `callback_dispatch`, and
`ops_cadence` heartbeats newer than the high-resolution cutoff captured
immediately before worker startup. Generic `/health/operational-ready` runs only
after that release-specific evidence passes.

Before migration begins, the deploy may restore the prior application only when
its images, Compose project, external env state, containers, pointer, and public
health are all proven. Previous Compose runs execute in an isolated process
environment so new-release variables cannot override the previous env file;
restored tags must match their recorded old image IDs and formerly absent tags
must be proven absent again. Recovery explicitly recreates `postgres`, `redis`,
`proxy`, `frontend`, `api`, `worker`, `callback-worker`, and `ops-worker` and
binds every recovered container's Compose image reference and actual `.Image`
to the unique old SHA256 recorded in the rollback map. A mismatch stops the
recovery generation and retains `.deploy-lock`. Once migration begins, any failure is fail-closed: do not
automatically start the old application against the possibly changed schema.
Stop public/write services, restore the prior `current` pointer, and write the
restricted failure marker for operator recovery. If stopped services, pointer,
or failure evidence cannot be proven, keep `.deploy-lock`; do not delete it to
force a retry.

After success, retain the new release's external `env.deploy` as matched release
state. Remove the temporary rollback-image map and its private rollback tags;
do not remove the per-release env state with them.
Once the new runtime has passed activation checks, an incoming, rollback-tag,
rollback-map, stale-marker, or lock cleanup failure is post-commit
terminalization failure: keep the healthy new `current`, return nonzero, retain
the rollback map and `.deploy-lock`, and repair from the restricted failure
marker. Do not start an old-runtime rollback. Report success only after every
tag/map cleanup and lock release is proved.

## Signed Runtime Smoke Semantics

The formal release smoke follows the current hosted runtime contract. It does
not call retired `/v1/addon/*` projection surfaces.

Operator interpretation rules:

- `site_id / key_id / secret` identify a real provisioned, active site API key.
- signed `GET /v1/catalog/models` confirms the public catalog read path.
- signed `POST /v1/runtime/execute` confirms the production provider
  configuration can execute a real hosted runtime request.
- signed `GET /v1/runs/{run_id}` and `/result` confirm run lookup and result
  retrieval through the current runtime contract.
- signed `GET /v1/stats/profiles/{profile_id}` and `/v1/usage/summary` confirm
  runtime detail and usage evidence remain readable.
- missing signed runtime credentials are a release-blocking configuration error.

Manual refresh guidance:

- WordPress local refresh actions must remain local cache or service-status
  reads only.
- Release evidence must come from the signed runtime smoke and internal
  observability endpoints, not from retired addon projection endpoints.
- If runtime smoke fails, inspect provider health, site/key lifecycle,
  entitlement, and runtime worker logs before changing WordPress-side controls.

## Secret Rotation

### Admin bootstrap token

1. Generate a new `NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN`.
2. Update the deploy secret store.
3. Restart `api`.
4. Verify `POST /admin/auth/bootstrap` succeeds with the new token and fails with the old token.
5. Record the rotation window in operator notes.

### Internal service token

1. Generate a new `NPCINK_CLOUD_INTERNAL_AUTH_TOKEN`.
2. Update the deploy secret store for `api`, `frontend`, `worker`, `callback-worker`, and `ops-worker`.
3. Restart those services together.
4. Verify `GET /health/ready` and `GET /internal/service/observability/summary` with the new token.
5. Verify old-token requests fail closed.

### Session invalidation

1. Rotate `NPCINK_CLOUD_ADMIN_SESSION_SECRET` to invalidate `/admin/*` sessions.
2. Rotate `NPCINK_CLOUD_PORTAL_JWT_SECRET` to invalidate `/portal/*` sessions.
3. Restart `api` and `frontend`.
4. Verify stale cookies no longer access `/admin/session` or `/portal/v1/session`.

### P1-E06 persisted-encryption dual-domain cutover

Neither the Service Settings pair
`NPCINK_CLOUD_SERVICE_SETTINGS_SECRET` /
`NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID` nor the Runtime Data pair
`NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET` /
`NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID` is an ordinary rotatable
configuration value. Never change either pair through the normal
secret-rotation or deploy-and-restart path. A direct change can strand
persisted ciphertext.

Each target root must be the canonical padded URL-safe Base64 encoding of 32
random bytes. Each domain has its own valid, non-secret key ID; the two target
roots and two IDs must be distinct. All four backend services (`api`, `worker`,
`callback-worker`, and `ops-worker`) own both target pairs. `frontend` owns
neither pair.

The first raw-ciphertext migration is a one-time P1-E06 dual-domain operation.
Use the single fail-closed orchestrator; do not reproduce its migration,
backup, restore, key rewrite, pointer, worker, or cleanup sequence by hand.

#### Controlled production CVE acceptance gate

Before staging or any production-host mutation, follow
`docs/python-3-14-6-controlled-production-validation-risk-decision-2026-07-21.md`.
After the final Linux/AMD64 bundle has a fresh passed scan and successful
same-bundle double replay, create the bundle-external
`npcink.controlled_production_cve_risk_acceptance.v1` file in the trusted
operator evidence store. It must be owner-only mode `0600`, use
`status=accepted_by_operator` and `scope=controlled_production_validation_only`,
and bind the final commit, tree, outer bundle checksum, scan-index checksum,
API scan-receipt checksum, allowlist checksum, exact three findings, zero
unallowlisted blocking findings, fresh NVD/CISA check, operator, time, and
2026-08-05 expiry. Record the acceptance file's SHA-256 separately.

The operator must manually compare those values with the bundle manifest,
outer checksum, `release/image-scan/scan-index.json`,
`release/image-scan/api.receipt.json`, and embedded allowlist. Absence,
malformation, mismatch, expiry, changed threat intelligence, or changed scan
evidence is a hard stop. GA is not authorized. The deployment, image-scan, and
P1-E06 tooling do not consume this acceptance, so a successful script exit
cannot replace this manual pre-mutation gate.

This acceptance is not `p1_e06_off_host_backup_receipt.v1`. The CVE acceptance
binds an exact release artifact and operator risk decision; the later P1-E06
receipt is machine-consumed proof that the database backup was copied to and
verified on independent storage. Both gates are required.

1. From the trusted operator workstation, stage the already-built exact bundle
   with `deploy/deploy-to-ssh-host.sh --stage-only`. Set the production host
   release-tool interpreter explicitly. Stage-only accepts only its mode,
   bundle/platform, SSH connection, host-Python, and managed-root inputs; do
   not supply env, base URL, site, key, model, provider, member, migration,
   refresh, seed, smoke, or ordinary-deploy inputs:

   ```bash
   unset NPCINK_CLOUD_ENV_FILE
   export NPCINK_CLOUD_DEPLOY_HOST_PYTHON=/usr/bin/python3.11
   bash deploy/deploy-to-ssh-host.sh \
     --stage-only \
     --skip-bundle-build \
     --bundle-path dist/deploy-bundle.tgz \
     --image-platform linux/amd64 \
     --ssh-host "${SSH_HOST}" \
     --ssh-user "${SSH_USER}" \
     --identity-file "${SSH_IDENTITY_FILE}" \
     --host-python /usr/bin/python3.11 \
     --remote-dir /opt/npcink-ai-cloud
   ```

   Accept only the machine-readable `staged_release=/absolute/release-path`
   output. Stage-only uploads and verifies the archive, safely extracts it, and
   runs the bundle pre-load check. It releases its own lock without resolving
   or changing `current`, creating release env state, loading images, invoking
   Docker, stopping services, running migrations, or starting traffic. Failure
   removes the unverified release and incoming files. Ordinary deploy remains a
   different path. The remote Python `>=3.11` check runs before remote mkdir,
   upload, or lock. Local/archive preflight failures create no remote object;
   later stage-only failure removes its incoming object, partial release, and
   lock before returning nonzero.
2. Recheck and close the independent Edge hard gate. Record the current
   release, source database revision `20260710_0058`, both old-root recovery
   owners,
   exact Linux/AMD64 bundle checksum, and rollback owner. The verified staged
   directory may exist already, but do not start the cutover or mutate an image
   until the Edge gate is complete. Normalize the managed root to `root:root`,
   prove it has no group/world-writable path, and create
   `/var/backups/npcink-ai-cloud` plus `/run/npcink-ai-cloud` as root-owned mode
   `0700` directories before invoking the cutover.
3. On the production host, create a separate untracked Edge-readiness env at
   `/run/npcink-ai-cloud/p1-e06-edge-readiness.env`, outside the managed release
   tree, root-owned and mode `0600`, with exactly these five non-secret keys:

   ```text
   NPCINK_CLOUD_EXTERNAL_EDGE_READY=true
   NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH=/etc/letsencrypt/live/cloud.npc.ink/fullchain.pem
   NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH=/var/lib/npcink-ai-cloud/edge/certificate-renewal-readiness.json
   NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER=certbot-renew.timer
   NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH=/etc/letsencrypt/renewal-hooks/deploy/reload-nginx
   ```

   Do not edit the active env directly. The P1-E06 orchestrator freezes this
   exact file and the original current env while holding `.deploy-lock`, proves
   that only these five keys change, fsyncs the lock owner and recovery
   directory chain, atomically publishes the augmented env,
   and writes value-free `p1_e06_edge_readiness_env_handoff.v1` digest evidence.
   Handled pre-migration failures and catchable `HUP`/`INT`/`TERM` signals
   restore the original env bytes. An uncatchable `SIGKILL` or host power loss
   leaves the persistent snapshot and deploy lock for manual recovery. Once
   migration starts, the original `.current-env.snapshot` and its digest remain
   part of the mandatory whole recovery point.
4. On the production host, create the untracked maintenance env outside the
   release tree, mode `0600`, with exactly these six keys. Keep values out of
   shell history, command arguments, logs, and Git:

   ```text
   NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET=<canonical-base64-32-byte-target-root>
   NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID=<target-key-id>
   NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET=<old-runtime-root>
   NPCINK_CLOUD_SERVICE_SETTINGS_SECRET=<canonical-base64-32-byte-target-root>
   NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID=<target-key-id>
   NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET=<old-service-settings-root>
   ```

   The two `*_OLD_ROOT_SECRET` values are maintenance inputs only. They may be
   passed to `dry-run` and `apply`, never to `inventory`, new-key-only
   `verify`, or the activated runtime. The orchestrator freezes this exact
   six-key file under `.deploy-lock`. A post-migration/pre-activation failure
   retains `.maintenance-env.snapshot` and records its SHA-256 in
   `.cutover-failed`; a variable-name list without that snapshot is not a
   complete recovery point. Pre-migration failure and successful activation
   remove the frozen private copy.

5. Run the one-time orchestrator in the foreground with the three exact
   acknowledgements. It prepares exact images through the governed
   `remote-load-and-up.sh` `prepare-only` mode, then stops and fences public
   services plus `api`, `worker`, `callback-worker`, and `ops-worker`. The
   prepare-only helper is intentionally allowed inside this orchestrator; do
   not call a traffic-starting load mode as a staging shortcut.

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

6. The orchestrator publishes a fresh
   root-owned mode-`0400` custom-format backup and checksum, atomically writes
   its mode-`0600` handoff marker under the staged
   release's external evidence directory, and waits in the same process. It
   does not accept an ordinary same-host copy as off-host evidence. From the
   trusted workstation, pull both backup files with `scp` to independent
   storage and verify SHA-256 locally. Create a receipt containing exactly:

   ```json
   {
     "contract": "p1_e06_off_host_backup_receipt.v1",
     "status": "passed",
     "backup_sha256": "<verified-sha256>",
     "off_host_copy": true
   }
   ```

   Upload the receipt to a temporary sibling path, set it mode `0600`, then
   atomically rename it to the exact receipt path printed by the waiting
   process. The final path must not have existed, must not be a symlink, and
   must be owned by the cutover operator. Never manufacture the receipt before
   the independent pull and local checksum verification. After validation, the
   orchestrator persists an immutable evidence copy named
   `off-host-receipt-verified.json` together with the source receipt path and
   receipt SHA-256. The terminal result carries that receipt digest; deleting
   or replacing the transient upload must not erase the validated evidence.
7. After accepting the receipt, the same process proves an independent
   PostgreSQL 16 restore and rehearses `0058 -> 0068`. Against that restored
   copy it runs `inventory -> dry-run -> apply -> verify` separately through
   `python -m app.dev.reencrypt_runtime_data` and
   `python -m app.dev.reencrypt_service_secrets`. Evidence is count-locked to
   18 Runtime Data rows (17 site signing secrets plus one Addon connection
   payload), 12 service-secret ciphertexts (eight provider connections plus
   four service-setting secret entries), and 30 ciphertexts in total. Each `apply` owns one
   independent database transaction; completion means that both applies and
   both new-key-only verifies succeeded. The process then removes
   the disposable restore resources and only then switches production
   `postgres` and `redis` to the exact target bundle image IDs. It proves both
   container image IDs, both health checks, and that PostgreSQL remains at
   `0058` before production migration begins. Every API one-off uses the
   governed `release-one-off` stopped candidate: `up --no-start --pull never
   --no-build --no-deps --force-recreate`, exact image/never-started proof,
   start of the captured ID, then `docker exec -i --env VARIABLE_NAME` with
   variable names only. Secret values and env-file run options remain
   forbidden. Runtime Compose `pull_policy: never` plus the staged image-ID
   proof binds every one-off to the exact API image. The first raw-ciphertext cutover
	   intentionally omits `--old-key-id`. Production repeats both count-locked
	   four-phase sequences inside the same writer fence and backup/restore window.
	   Only the matching Runtime Data `dry-run`/`apply` receives
	   `--old-root-env NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET`; every `apply`
	   records `--confirm-maintenance-window`. A future reviewed `rde.v1`
	   rotation must positionally pair that root with
	   `--old-key-id "${OLD_RUNTIME_DATA_KEY_ID}"` inside its dedicated
	   orchestrator.
	   The Runtime Data sequence ends with
   `python -m app.dev.reencrypt_runtime_data verify`; the Service Settings
   sequence ends with `python -m app.dev.reencrypt_service_secrets verify`.
   Only the matching service `dry-run`/`apply` receives
   `--old-root-env NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET`.
   The sorted non-secret row-identifier sets are also frozen by canonical-JSON
   SHA-256: Runtime Data
   `675cce444dbbf801bc8ab7fb35b717888c878e062097e5fb7f2f5f110e5a764c`
   and Service Settings
   `e5010d2b0a2afe22b7729c4c2395c91001a078e282abee87f03a5f0289aa0bf6`.
   A count-preserving replacement therefore fails closed. If an intentional
   pre-cutover inventory change occurs, stop and approve a newly reviewed
   digest instead of bypassing the check.
8. The orchestrator writes both target roots and key IDs only to the staged
   external env, atomically activates the staged release, verifies API and new worker
   generation readiness, restores traffic, and validates the active release.
   Immediately after that validation it durably publishes
   `activation-commit.json`; this is the explicit irreversible activation
   commit point. Only after the commit point may it remove the rollback
   map/private tags, atomically publish the final mode-`0600`
   `.release-state/<staged-release-name>/p1-e06-runtime-data-cutover/cutover-result.json`.
   It then publishes the global activation receipt bound to both the activation
   commit and cutover-result digests, releases `.deploy-lock`, and only then
   marks the operation complete. A successful command exit alone is insufficient.

Failure recovery has two non-interchangeable boundaries:

- Before production migration starts, the old application may be restored
  automatically after the failure evidence is written. If production data
  services were not switched, prove their existing health and `0058`, then
  restore the prior application and traffic. If they were switched to target
  image IDs, first restore the recorded PostgreSQL and Redis tags, recreate and
  prove those dependencies healthy with PostgreSQL still at `0058`, and only
  then restore the prior API, workers, frontend, and proxy. Each restored
  application container must match the previous Runtime Compose reference and
  rollback-map SHA256; any mismatch re-fences all application services. Do not claim that
  writers remain stopped when this verified pre-migration recovery succeeds.
- Once production migration starts, do not downgrade and do not restart old
  code against the new or partially changed schema. Restore the whole fresh
  `0058` database dump, previous application release, the original external env
  from the retained `.current-env.snapshot`, and both old roots from the
  digest-bound `.maintenance-env.snapshot` together.
  Although the Runtime Data and Service Settings
  `apply` phases are independent transactions, failure of either phase or any
  later pre-activation step requires this same whole recovery point; retaining
  only one committed domain is forbidden. A code-only, env-only, root-only, or
  database-only rollback is forbidden. Migration `0061` removes legacy
  media/audio tables, so an Alembic downgrade cannot reconstruct the
  pre-cutover bytes.

Before the activation commit point, every unrecovered failure leaves
`/opt/npcink-ai-cloud/.cutover-failed` and retains `.deploy-lock` for operator
recovery; passed and failed evidence must never coexist. After the activation
commit point, cleanup, private/global evidence, or unlock failure is terminalization
incomplete, not a rollback signal: keep the healthy new runtime and pointer,
do not restore tags or stop writers, and retain or reacquire the lock with
`outcome=activation_committed_terminalization_incomplete` and
`recovery=do_not_rollback_healthy_active_runtime`. Repair terminal evidence
without destructive rollback.

#### Future `rde.v1` to `rde.v1` rotation

This is a later, separately approved maintenance path, not an alternative way
to execute the first P1-E06 cutover. Keep the same backup, off-host receipt,
writer fence, restore rehearsal, and whole-database rollback requirements.
There is intentionally no copy/paste Compose command for this future path.
Before any such rotation, add and review a dedicated orchestrator that reuses
the deployment-lock owner proof, global `release-one-off` lock, exact stopped
candidate/image proof, protected names-only environment handoff, cleanup
proof, and the full P1-E06 recovery gates. A naked Compose one-off is not an
approved production entry point.

Positionally pair every additional `--old-root-env` and `--old-key-id` only
when preflight evidence proves multiple historical envelopes.
Inventory and new-key-only `verify` do not receive any old root; only
`dry-run` and `apply` may receive
`NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET`.
During the first P1-E06 Service Settings migration, the matching old-root
exposure rule applies to `NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET` and
`python -m app.dev.reencrypt_service_secrets`. That tool currently supports
only raw Fernet to `sse.v1`; it does not accept an old `sse.v1` key ID. Any
future `sse.v1` rotation requires a separately designed and approved contract.
Normal runtime has no legacy or dual-read path. It accepts only active `rde.v1`
and `sse.v1` envelopes and rejects raw Fernet. Migration-only tools remain
offline maintenance boundaries.

#### Retained `release-one-off` lock recovery

`/opt/npcink-ai-cloud/.release-state/.release-one-off.lock` is recovery
evidence, not a stale-file hint. Never remove the lock first. If
`.deploy-lock` also exists, stop and recover that deployment from its failure
marker before touching either lock. Otherwise:

1. Run the read-only global query `docker container ls -a --no-trunc --filter
   "label=com.docker.compose.service=release-one-off"`; do not scope it to one
   Compose project.
2. Inspect every captured full ID, then remove only those exact one-off
   containers. Repeat the global label query and exact-ID queries; any query
   failure is ambiguous and keeps the lock.
3. Check the configured temporary root for a root-owned, private
   `npcink-release-proof-stdin.*` directory. Remove it only after the matching
   container is proved absent; do not use an unbounded wildcard cleanup.
4. Prove the lock itself is root-owned, non-symlink, empty, and mode `0700`.
   Only then remove that exact empty directory with `rmdir`. If any proof fails,
   retain it and record manual recovery evidence.

## Worker Operations

### Restart workers

There is no standalone production worker-restart entry point. Recreate the
runtime through the governed release transaction from the trusted workstation,
using the already verified bundle and a complete protected env file:

```bash
source deploy/workspace-target.env.sh
pnpm run deploy:ssh -- \
  --skip-bundle-build \
  --env-file /absolute/path/to/protected.env.deploy \
  --skip-seed \
  --skip-smoke
```

Do not edit the active release env or invoke Compose restart directly. A real
outage that cannot wait for this path is a production break-glass event and
must be backported and evidenced under the release policy.

Then verify:

- `GET /health/operational-ready` returns `200`
- `GET /internal/service/observability/summary` shows fresh worker heartbeats
- `GET /internal/service/ops/cadence` shows non-fresh tasks recovering toward fresh

## Resource Tuning Baseline

Tune resources by preparing a complete protected env file off-host and applying
it through the governed deployment shown above. Never mutate the current
release's external env in place. This keeps configuration, exact images,
rollback state, and readiness evidence in one release transaction.

Primary knobs:

- `NPCINK_CLOUD_API_WORKERS`: gunicorn API worker count. Keep it within the
  release host CPU and memory budget.
- `NPCINK_CLOUD_RUNTIME_WORKER_POLL_SECONDS`: runtime queue polling cadence.
- `NPCINK_CLOUD_RUNTIME_CALLBACK_WORKER_POLL_SECONDS`: callback dispatch polling
  cadence.
- `NPCINK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS`: heartbeat freshness window
  for worker health checks.
- `NPCINK_CLOUD_OPS_CADENCE_POLL_SECONDS`: ops cadence loop frequency.
- `NPCINK_CLOUD_RETENTION_CLEANUP_INTERVAL_SECONDS`: retention cleanup cadence.
- `NPCINK_CLOUD_USAGE_ROLLUP_INTERVAL_SECONDS`: usage rollup cadence.
- `NPCINK_CLOUD_ROUTER_DIAGNOSTICS_INTERVAL_SECONDS`: router diagnostics cadence.
- `NPCINK_CLOUD_LATENCY_PROBE_INTERVAL_SECONDS`: latency probe cadence.
- `NPCINK_CLOUD_ALERT_PROVIDER_DEGRADATION_INTERVAL_SECONDS`: provider
  degradation alert cadence.
- `NPCINK_CLOUD_PROVIDER_HEALTH_SCAN_INTERVAL_SECONDS`: provider health scan
  cadence.
- `NPCINK_CLOUD_ARTIFACT_RECONCILIATION_INTERVAL_SECONDS`: read-only artifact
  inventory reconciliation cadence.
- `NPCINK_CLOUD_ARTIFACT_RECONCILIATION_SAFETY_WINDOW_SECONDS`: minimum object
  age before an unreferenced object is reported as eligible; C2a never deletes it.
- `NPCINK_CLOUD_ARTIFACT_RECONCILIATION_PAGE_SIZE`: bounded store and database
  inventory page size, from 1 through 500.
- `NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED`: destructive orphan cleanup;
  it defaults to `false` and must remain false until P3-B4C3 is accepted.
- `NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_BATCH_SIZE`: per-cadence candidate cap,
  from 1 through 100; each candidate receives its own non-blocking EX fence.

The artifact volume root must remain stable and writable only by the service
owner or trusted operators. Do not replace its mount, shard directories, or
private publication-fence file while API/runtime/ops workers are running.
C2a `orphan_eligible` remains age evidence and never authorizes manual
deletion. Keep C2b automatic cleanup off until PostgreSQL 16 multi-connection
and real named-volume proof is complete. Before any later enablement, verify
service-account ownership and safe modes for root/shards/files, private `0600`
single-link generation marker and lock files, stable mount/root identity, and
that every namespace writer obeys the advisory fence. See
[`docs/media-derivative-operations-runbook-v1.md`](../docs/media-derivative-operations-runbook-v1.md#orphan-cleanup-enablement-gate)
for the full enablement and rollback checklist.

After any resource or cadence change:

1. Complete the governed deploy and retain its exact bundle and rollback
   evidence.
2. Verify `GET /health/operational-ready`.
3. Verify `GET /internal/service/observability/summary` shows fresh heartbeats.
4. Verify `GET /internal/service/ops/cadence` has no unexpected stale tasks.
5. Run one signed runtime smoke when worker or provider cadence changed.
6. Record the changed variables and rollback values in operator notes.

### Callback backlog recovery

1. Check `GET /internal/service/observability/summary`.
2. Inspect `runtime.summary.callback` and `runtime.backlog`.
3. If `callback.dispatching_stale` or overdue callbacks persist, use the
   governed release transaction under **Restart workers** to recreate the
   runtime from its verified bundle and protected env.
4. Do not issue a standalone `callback-worker` restart; an outage that cannot
   wait for the governed transaction is a documented break-glass event.
5. Recheck `/internal/service/runtime/diagnostics/runs?issue_kind=callback_overdue`.
6. Confirm backlog declines before broader intervention.

### Manual retention cleanup

Use only when cadence is stale or blocked:

```bash
curl -X POST "$NPCINK_CLOUD_BASE_URL/internal/service/runtime/retention/cleanup" \
  -H "X-Npcink-Internal-Token: $NPCINK_CLOUD_INTERNAL_AUTH_TOKEN" \
  -H "Idempotency-Key: manual-retention-cleanup-$(date +%s)"
```

Then verify:

- `GET /internal/service/ops/cadence`
- `GET /internal/service/audit-events?event_kind=runtime.retention_cleanup&limit=5`

## Database Rollback

Database rollback is a matched release-recovery operation, not a standalone
database restore followed by generic service restarts. Before release, retain
the exact backup, application bundle, protected external env, image identities,
release pointer, and rollback evidence as one recovery set. If rollback is
required:

1. Fence public traffic and every database writer.
2. Restore the known-good snapshot with the host-specific reviewed procedure.
3. Re-establish the matched application revision, release pointer, protected
   env, and exact image identities through the governed recovery path.
4. Keep the deployment lock and traffic fence if any restore, image, container,
   or readiness proof is ambiguous. Do not use bare Compose restarts.
5. Verify `/health/ready`, `/health/operational-ready`, and
   `/internal/service/observability/summary` before reopening traffic.

For the P1-E06 dual-domain encryption cutover, this general database-only
procedure is insufficient. Restore the matched old backup, old application revision,
old external env, and both old roots together as specified in
**P1-E06 persisted-encryption dual-domain cutover**.

## Provider Failover

1. Inspect `providers.degraded_provider_ids` in `GET /internal/service/observability/summary`.
2. Cross-check `alert.provider_degradation_cadence` freshness in `GET /internal/service/ops/cadence`.
3. Update hosted provider connections, credentials, and hosted routing in the
   Cloud admin surface. WordPress remains authoritative only for local
   abilities, workflows, prompts, approvals, and final CMS writes.
4. Confirm the selected provider for the release host has a real credential configured before retrying runtime smoke.
5. Re-run one real runtime request and confirm provider health recovers in the next cadence window.

If real runtime smoke returns `runtime.provider_not_configured`, treat it as a release-blocking environment failure, not as a soft smoke warning.

## Cadence Stale Recovery

1. Check `GET /health/operational-ready`.
2. Inspect `GET /internal/service/ops/cadence`.
3. If one or more tasks are stale, use the governed release transaction under
   **Restart workers** to recreate the runtime; do not issue a standalone
   `ops-worker` restart.
4. If staleness persists, inspect `service_audit_events` for the failing cadence task.
5. If runtime smoke fails after cadence recovery, inspect provider health,
   runtime diagnostics, site/key lifecycle, and entitlement evidence before
   changing WordPress-side controls.
6. After recovery, verify `non_fresh_total == 0`.

## Trace Sink Check

1. Read `data.tracing.otlp_endpoint`, `data.tracing.otlp_configured`,
   `data.tracing.trace_query_url`, and `data.tracing.trace_query_configured`
   from `GET /internal/service/observability/summary`.
2. Open the configured query URL or trace UI.
3. Trigger a fresh internal request such as `GET /health/operational-ready`.
4. Confirm a new trace for `npcink-ai-cloud` appears in the sink.
5. If either URL is absent, export fails, or no fresh trace is queryable, the
   formal release is not closed. Ordinary non-release runtime may leave both
   values empty.

## Release Gate

Before a formal release, operators must start from `deploy/RELEASE_CHECKLIST.md`.

The release gate is divided into:

- repo ready
- env required
- operator required
- smoke required

`repo ready` can be closed by repository evidence. `env required`, `operator required`, and `smoke required` must be closed on the actual release host. If any item in those categories is incomplete, the release is blocked.

`deploy/release-smoke.sh` is the formal smoke gate. Do not replace it with a second release entry point or a partial manual checklist.

Operators must be able to answer all of these from current data:

- Is the API ready?
- Are `worker`, `callback-worker`, and `ops-worker` alive?
- Is execution backlog separated from callback backlog?
- Are managed cadence tasks fresh?
- Is provider health fresh, and which provider is degraded?
- Is OTLP tracing wired to the configured external endpoint and is a fresh
  trace queryable?
- Has one real signed runtime request succeeded against the production provider configuration?
- Do signed run lookup, result retrieval, stats, and usage evidence remain readable?
