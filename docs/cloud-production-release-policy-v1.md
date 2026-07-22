# Cloud Production Release Policy v1

Status: active lightweight gate.

Purpose: define the low-cost production release rules for the current early
validation phase. This policy is a human/process gate until GitHub branch
protection and environment approval are worth paying for.

## Scope

This policy covers changes that may reach `https://cloud.npc.ink`.

It does not create a second WordPress control plane, approval system, ability
registry, workflow registry, local prompt truth, or local runtime-policy
authority. Cloud remains the hosted runtime/service-plane layer and may own
the hosted provider connections, credentials, routing, and execution required
by that runtime.

## Branch Model

- `master` is the development integration branch.
- `production` is the production release source.
- feature and fix branches merge to `master` first.
- production releases are promoted from `master` to `production`.

Do not directly edit production application code on the server. Production
database credentials and runtime root secrets are authoritative only in the
protected structured configuration under `shared/config/`; they are never
copied into `.env.deploy`. The deploy environment remains a protected source
for non-secret host, edge, provider, and runtime-tuning inputs. Database-target
or runtime-root changes require their governed operator procedure, not an
in-place Compose restart. Other server-side changes are limited to the
documented first-install/key-rotation helpers and emergency break-glass fixes
that must be backported to Git immediately.

The former P1-E06 Edge-readiness handoff exception is closed as an ordinary
deployment dependency by the PostgreSQL 18 reset. Its evidence and procedure
remain documented in the historical section below; they do not authorize an
active-env edit and are not prerequisites for a fresh PG18 installation or a
later PG18 deployment.

Branch divergence is expected: `production` records the deployed release while
`master` continues development. A production-only patch must not remain an
unexplained long-term fork. Before the next promotion, classify it as already
equivalent on `master`, forward-port it to `master`, or document why the old
deployment behavior is obsolete. Do not merge the accumulated `production`
history back into `master` merely to make the branch graph look aligned.

## Current Promotion Gates

Before merging a feature or fix to `master`, record the focused module and
non-goals, confirm the Cloud/WordPress ownership boundary, keep secrets out of
Git, and run the narrowest relevant local gates plus CI. Before promoting
`master` to `production`, additionally require:

- green CI for the exact `master` commit and an intentional release scope;
- the applicable release checklist, exact-bundle evidence, known rollback
  boundary, and no direct server code edit as source truth;
- protected server-side configuration and credentials absent from the release
  archive, GitHub logs, process arguments, and `.env.deploy`;
- the production-promotion PR sentence
  `Approved for production validation by operator.`;
- manual production workflow dispatch and Environment approval after the exact
  `production` revision passes CI.

Recommended repository gate:

```bash
pnpm run check:release-policy
```

## Current PostgreSQL 18 Release Contract

The current production database contract is a fresh external Alibaba Cloud RDS
PostgreSQL 18 database initialized by the one-time installer. The application
and release tooling must fail closed unless all of the following are true:

- `install-state.json` is an explicit, protected state created only by the
  root-owned first-install helper;
- `complete` carries `database_contract=pg18_empty_initialization.v1` and the
  SHA-256 of the exact protected runtime configuration;
- the candidate API image loads that protected configuration, resolves the RDS
  hostname only to approved private addresses, verifies TLS with the stored CA,
  observes PostgreSQL major version 18, and proves exactly one current Alembic
  revision at the candidate head or one of its known ancestors before old
  writers are stopped;
- after old writers stop, the governed migration must establish the exact sole
  candidate head before the candidate API or workers start;
- production Compose contains no PostgreSQL service, image, volume, password,
  database URL, or database startup dependency;
- workers remain behind the install-state gate and cannot connect before
  `complete`.

A first install is a distinct release lifecycle. The deploy stops but preserves
the previous local PostgreSQL container and volume, pins the previous release
and images, and writes a protected pending marker. A second deployment and
safe-prune are forbidden until the operator either rolls back while setup is
still pending or explicitly finalizes a completed, accepted install. Finalize
publishes the permanent completion sentinel before idempotent cleanup and keeps
pruning blocked until cleanup finishes.

After installation, the ordinary deployment order is:

```text
validate exact bundle and candidate images
-> validate complete-state/config digest
-> candidate-image RDS PostgreSQL 18/TLS/Alembic preflight
-> stop public and write-capable application services
-> run the candidate migration against RDS
-> activate API
-> activate workers and prove heartbeats
-> pass operational readiness
-> restore frontend/proxy traffic
```

Once a migration starts, old code must not automatically connect to the changed
database. Recovery requires a matched application release, protected runtime
configuration, and RDS restore point. The validation Basic Edition instance is
not approved for real users, paid workloads, or irreplaceable data; upgrade it
to a high-availability edition first.

The required gates for this contract are the focused Setup/Auth/frontend tests,
PostgreSQL 18 schema and semantic proof, production Compose and exact-bundle
contracts, release-policy checks, current CI, real RDS private/TLS smoke, and a
WordPress text/media round trip. The Python image CVE exception must be closed
in a separate release before this database cutover is authorized.

The canonical procedures are:

- [Cloud First Install Contract](cloud-first-install-contract-v1.md);
- [Cloud First Install with Alibaba RDS PostgreSQL 18](cloud-first-install-rds-pg18-runbook.md);
- [ADR-022](decisions/022-one-time-cloud-install-and-rds-postgresql-18.md).

## Historical PG16 and P1-E06 Policy (non-normative)

Everything from this heading through the next `Emergency Rule` heading is the
preserved pre-PG18 production policy. It records how the former local
PostgreSQL 16 and P1-E06 cutover were governed, but it is no longer an active
ordinary-deployment requirement and must not be used to reopen compatibility
paths or require legacy activation receipts.

### Pre-refactor Production Reconciliation

The production-only patches below were reconciled against development
`master` on 2026-07-14. Their behavior is present in the current development
line with contract coverage, so no reverse merge or duplicate cherry-pick is
required:

- `9aca0dc0`: deployment workflows call the SSH deploy script directly;
- `9c160ed5`: remote deploy arguments are shell-quoted;
- `5a2cf130`: production proxy preserves forwarded host/protocol headers;
- `6dff10a5`: ready probes derive the required host/origin headers;
- `559e032f`: `/terms` resolves the static terms entrypoint and is smoke-tested;
- `4e532f0c`: admin bootstrap is routed directly to the API with forwarded origin;
- `c9f3036b`: frontend runtime backend variables are not frozen into the build.

This is a semantic reconciliation record, not a claim that the two branch
histories or trees should be identical.

### Historical Required Gates Before `master`

For normal feature and fix PRs:

- describe the focused module and explicit non-goals;
- confirm Cloud boundary impact, especially that Cloud is not becoming a
  WordPress write owner or second local control plane;
- keep public legal and policy pages under `site/terms/*` in the production
  static release path when those pages change;
- state explicitly when needed: Cloud is not becoming a WordPress write owner;
- run the narrowest useful local gate, or explain why GitHub CI is the gate;
- keep production secrets, SMTP passwords, provider keys, DB credentials, and
  internal tokens out of Git.

Recommended command:

```bash
pnpm run check:release-policy
```

### Historical Required Gates Before `production`

Before promoting `master` to `production`:

- `master` CI is green;
- the promotion contains only intended release changes;
- `deploy/RELEASE_CHECKLIST.md` has no newly relevant unchecked blocker for the
  release scope;
- no direct server code edit is being used as source truth;
- public static legal pages, including `/terms/en/terms.html`, remain covered
  by the deploy smoke when the release changes legal, policy, or proxy files;
- rollback path is known before merging;
- production secrets remain server-side or in GitHub Secrets, not committed.
- the frontend does not inherit the backend `.env.deploy`; only its reviewed
  runtime allowlist may be present. Both Service Settings and Runtime Data
  target root/key-ID pairs belong to `api`, `worker`, `callback-worker`, and
  `ops-worker`; all four variables must remain absent from `frontend`;
- the release payload contains no `.env.deploy`; each managed release resolves
  its backend environment from
  `${REMOTE_DIR}/.release-state/<release-name>/env.deploy`, with both state
  directories mode `0700` and the env file mode `0600`. Post-load image identity
  is stored only at the fixed sibling path
  `${REMOTE_DIR}/.release-state/<release-name>/target-daemon-images.json`, also
  mode `0600`; that path is derived from the release name and is not
  configurable, and the release name is part of the map's cryptographic
  binding;
- the old and new Compose project names must match before any image or container
  mutation, and the running old writers' actual Compose labels must match that
  project; an ordinary deploy must not silently rename the project and orphan
  old writers;
- a P1-E06 encryption cutover has count-only inventory/dry-run/apply/verify
  evidence for both domains and exactly 30 legacy rows: Runtime Data
  `18 = 17 + 1` and Service Settings `12 = 8 + 4`. It also has a
  checksum-verified and restore-tested backup plus the matching old code,
  external env, and both old-root recovery point;
- before P1-E06 is invoked, the independent production Edge topology hard gate
  proves active host NGINX, `nginx -t`, exact-host loopback-resolved HTTPS, and
  stopped retired Caddy; it also records a certificate-renewal owner, enabled
  automatic renewal service/timer,
  root-owned persistent deploy hook in `renewal-hooks/deploy`, successful
  renewal dry run and direct hook/reload execution, and at least 30 days of
  validity for both the named PEM and the leaf actually served by
  `127.0.0.1:443`. The two leaf SHA256 fingerprints must match. The exact
  NGINX TLS server must reference the matching Certbot live-lineage
  `fullchain.pem` and `privkey.pem` paths directly, never copied certificate
  files. Those live symlinks must resolve to root-owned non-symlink targets
  inside the same `/etc/letsencrypt/archive` lineage, with no group/other
  private-key permissions. Readiness must parse and evidence-bind the effective
  `nginx -T` certificate/key directives and prove their keypair match. Initial
  Edge activation is one remote transaction holding
  `/opt/npcink-ai-cloud/.deploy-lock`: it freezes old NGINX state and exact
  project-Caddy IDs, stops those IDs, validates the new NGINX Edge, and on any
  failure restores NGINX plus restarts/verifies only those original IDs.
  `--prepare-only` must restore the exact prior files and must not consume the
  only rollback evidence, stop Caddy, or switch traffic. Final Edge health is
  marked committed while the shared lock is still held; lock-release failure
  retains the healthy Edge, lock, and evidence and must never trigger a
  rollback. The operator then prepares the separate exact-five-key
  Edge-readiness input but does not edit the active env. P1-E06's first
  lock-held preflight durably snapshots the recovery anchors, publishes only
  those five keys to the active env, and re-verifies certificate readiness;
  neither image nor database mutation may begin before both handoff and verify
  pass. The exact
  staged release must generate fresh
  `npcink_cloud_certificate_renewal_readiness.v1` evidence as root with host
  Python `>=3.11`; the receipt is root-owned mode `0600`, expires after seven
  days, and is verified before formal image snapshot/tag/load or cutover work.
  For Alibaba Cloud Linux 3 the selected EPEL unit is
  `certbot-renew.timer`; tooling accepts another safe timer only when it is
  explicitly configured and evidence-bound. The active env must explicitly
  record `NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH`,
  `NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH`,
  `NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER`, and
  `NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH`; none has a formal-runtime
  default. The encryption cutover must
  not create or repair the public Edge. Pure stage-only archive upload/verification
  may precede this gate, but no image mutation or cutover command may;
- production release tooling uses an explicitly selected
  `/usr/bin/python3.11` host interpreter and verifies Python `>=3.11` before any
  remote mkdir, upload, or lock. This host contract is separate from the Cloud
  application image's Python `>=3.12` contract;
- `/opt/npcink-ai-cloud` is a root-managed `root:root` tree with no group- or
  world-writable managed path; `/var/backups/npcink-ai-cloud` and
  `/run/npcink-ai-cloud` are root-owned mode `0700` directories.

For the current early validation phase, the manual sign-off is:

```text
Approved for production validation by operator.
```

Put that sentence in the production promotion PR body until paid branch
protection/environment approval is enabled.

### Historical Deployment Rule

Merging or pushing to `production` runs validation only; it must never mutate
the host. After the exact `production` revision passes `Cloud CI`, an operator
manually dispatches `Deploy Production`, enters the exact approval sentence,
passes the GitHub `production` Environment approval, and lets the workflow
confirm a completed successful `Cloud CI` run for that exact production commit.
The workflow is `workflow_dispatch` only; there is no push or `workflow_run`
deployment path.

Production SSH host identity is pinned in the protected Environment through a
pre-verified `PROD_SSH_KNOWN_HOSTS` secret. The deployment workflow must not
derive trust with runtime `ssh-keyscan`; SSH and SCP require
`StrictHostKeyChecking=yes`. Host-key rotation is an explicit operator action
after independent fingerprint verification.

The ordinary production deploy is one serialized, fail-closed cutover. The
release payload must never contain `.env.deploy`; a separately uploaded or
previously protected env source is installed into the new release's external
state directory before the first mutation. The enforced order is:

```text
prepare exact images
-> stop old public and write-capable application services
-> start/retain PostgreSQL and Redis
-> migrate and refresh through exact-image one-off staged API containers
-> atomically point current at the new release
-> start and verify API
-> start workers and prove container stability plus heartbeat timestamps newer than the cutover cutoff
-> pass generic operational-ready
-> restore frontend/proxy traffic
```

The previous and new Compose project names and the actual old writer container
labels must match before image loading or container mutation begins.
`--skip-frontend-image` additionally requires exactly one running old frontend
to preserve; it is invalid for a first deploy or a missing frontend. Ordinary
production deployment is never an implicit host bootstrap: a missing managed
`current` release fails before image mutation. Before the first image load, the
deploy reads the current PostgreSQL Alembic revision through the frozen previous
release. Revision `20260710_0058` always fails and can advance only through the
P1-E06 orchestrator. Formal production dispatch additionally requires the
root-owned global P1-E06 activation receipt, its digest-bound complete
per-release evidence, and a current database revision that is `0068` or a
descendant proven from the staged bundle's Alembic graph. Receipt enforcement
is mandatory for every ordinary production deployment and is explicitly pinned
by the production workspace target. Only archive-only staging may omit it.
Once migration starts, any failure leaves public and
write-capable application services stopped; the deploy must not automatically
restart the old application against a possibly changed schema. Recovery must
prove stopped services, the restored `current` pointer, and a restricted failure
marker. Reconstructing the old release must isolate the new release environment
so only the previous env controls old Compose interpolation, and every restored
or removed image tag must be verified. If that evidence is incomplete, the
deployment lock remains for manual operator recovery. On success, retain the
per-release external env state and remove the temporary rollback-image map and
rollback tags.
After the new runtime has passed activation checks, failure to clean protected
incoming state, rollback tags, the rollback map, stale failure evidence, or the
deploy lock is a post-commit terminalization failure. It must not roll back the
healthy active runtime; it returns nonzero, writes restricted failure evidence,
and retains the rollback map and deploy lock. Success is reported only after
tag/map removal and lock release are each proved.

Ordinary migration/provider one-offs use the profiled `release-one-off` API
service. Compose pins that service to the recorded target-local daemon ID and
uses `up --no-start --pull never --no-build --no-deps --force-recreate` to
create exactly one stopped candidate. Post-load verification first proves
the loaded image's portable Config image ID and platform against the exact
bundle, then records the corresponding target-local daemon ID only in
`${REMOTE_DIR}/.release-state/<release-name>/target-daemon-images.json`.
Release tooling compares the current tag and stopped candidate's `.Image` with
this recorded target-local ID before starting that captured container ID. It
then rechecks the running container and executes the payload through
`docker exec -i` on the same ID before removing it.
One fixed mode-`0700` lock under the managed `.release-state` root serializes
one-offs across release directories. Signal cleanup is mandatory; incomplete
container or protected-stdin cleanup retains that lock for operator recovery.
Runtime Compose sets `pull_policy: never` for every explicit-image service.

The loader accepts only the explicit `prepare-only`, `data-only`, `api-only`,
`workers-only`, and `traffic-only` phases; no default or aggregate phase exists.
`prepare-only` loads and proves images but starts no service. Each subsequent
phase freezes all required daemon IDs from the fixed map, pins Compose to those
IDs, creates force-recreated candidates with
`up --no-start --pull never --no-build --no-deps --force-recreate`, captures exactly one stopped container ID per service, and verifies every candidate's
`.Image`. It then re-proves the complete phase's
governed tags against the map before using `docker start` on only the captured
IDs. The same container IDs and image IDs must still be running before any
health or readiness gate succeeds.

The Service Settings pair
`NPCINK_CLOUD_SERVICE_SETTINGS_SECRET` /
`NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID` and the Runtime Data pair
`NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET` /
`NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID` are exempt from ordinary
configuration-only rotation. Each target root must be canonical padded
URL-safe Base64 decoding to exactly 32 random bytes, and each domain has its own
valid key ID. The pairs may change only in one planned stopped-writer
maintenance window. The first dual-domain raw-ciphertext migration is executed
only by `deploy/runtime-data-encryption-cutover.sh`; it must not be reconstructed
as a manual sequence.

Prepare the exact Linux/AMD64 archive with
`deploy/deploy-to-ssh-host.sh --stage-only`. That mode rejects any env input,
uploads and pre-load verifies only the archive, releases its own lock, and
returns `staged_release=/absolute/release-path`. It must not inspect or change
`current`, create release state, call Docker, load images, stop or start
containers, migrate, refresh, seed, smoke, or restore traffic. The one-time
orchestrator may then use the governed `remote-load-and-up.sh` `prepare-only`
mode internally; this is not permission for an operator to invoke a
traffic-starting load mode as a shortcut.

Stage-only accepts only bundle/platform, SSH connection, managed-root, and
host-Python inputs. Its remote argument envelope contains no runtime or tenant
value. It verifies `/usr/bin/python3.11` at Python `>=3.11` before any remote
mkdir, upload, or lock, and cleans incoming/partial release/lock artifacts on
every later failure.

The orchestrator must keep secrets outside the bundle, require a mode-`0600`
maintenance env containing exactly six keys (two target root/key-ID pairs and
the two corresponding old roots):

- `NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET`;
- `NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID`;
- `NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET`;
- `NPCINK_CLOUD_SERVICE_SETTINGS_SECRET`;
- `NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID`;
- `NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET`.

The orchestrator freezes that exact six-key file under the lock. A
post-migration/pre-activation failure retains the root-owned mode-`0600`
maintenance snapshot and records its SHA-256 in `.cutover-failed`; naming the
two old-root variables without this bound snapshot is not recovery evidence.
Pre-migration failure and successful activation remove the private copy.

It separately requires `--edge-readiness-env` outside the managed release
tree. That root-owned mode-`0600`, non-symlink file contains exactly five
non-secret keys: `NPCINK_CLOUD_EXTERNAL_EDGE_READY=true` plus the certificate
path, certificate-readiness evidence path, renewal timer, and persistent deploy
hook path. Under `.deploy-lock`, the orchestrator freezes this input, snapshots
the original current env, proves that only those five keys change, atomically
publishes the augmented env, and records
`p1_e06_edge_readiness_env_handoff.v1` without values. The augmented digest is
the cutover baseline copied to the staged env. Before migration, handled
failures and catchable signals restore the exact original bytes. An
uncatchable `SIGKILL` or host power loss instead leaves the persistent snapshot
and deploy lock for manual recovery. After migration starts, the lock, original
snapshot, digest, and both old roots from the retained maintenance snapshot
remain part of the mandatory whole
recovery point. After activation commits, the healthy new runtime is never
rolled back merely to restore the former env.

It then stops and fences public plus all four writer services, publishes a fresh
custom PostgreSQL backup and checksum, and pauses in the same process for
independent off-host acknowledgement. The operator must pull the
backup and checksum with `scp`, verify SHA-256 on independent storage, then
atomically publish a new mode-`0600`
`p1_e06_off_host_backup_receipt.v1` receipt containing the matching checksum.
A same-host copy, pre-created receipt, or acknowledgement without that pull is
not backup evidence. Persist the validated receipt content, source path, and
receipt SHA-256 in `off-host-receipt-verified.json`; terminal evidence carries
that digest.

Only after the receipt may the script perform an independent PostgreSQL 16
restore and rehearse `0058 -> 0068`. In that same restore rehearsal and then in
production it separately runs count-locked `inventory`, `dry-run`, `apply`, and
new-key-only `verify` through `python -m app.dev.reencrypt_runtime_data` for 18
rows and `python -m app.dev.reencrypt_service_secrets` for 12 rows. Each
`apply` is an independent database transaction, but both applies and both
verifies are one 30-row activation gate. The gate also freezes each sorted
non-secret row-identifier set by canonical-JSON SHA-256; matching counts with a
different identity set must fail closed. An intentional inventory change
requires a newly reviewed digest, never a bypass. Before production migration, it then
switches PostgreSQL and Redis to exact target image IDs and proves both healthy
plus PostgreSQL still at `0058`. Every production/rehearsal API one-off uses
the governed `release-one-off` stopped candidate: Compose creates it with
`up --no-start --pull never --no-build --no-deps --force-recreate`, the host
proves its exact image ID and never-started state, starts that captured ID, and
passes only variable names to `docker exec -i --env VARIABLE_NAME`. Secret
values never enter arguments or an env-file run option. Runtime Compose
`pull_policy: never` and exact image-ID proof bind the command to the staged
image. Inventory and new-key-only `verify` receive no old root; each old
root is exposed only to its matching `dry-run` and `apply`. The first
raw-ciphertext cutover omits `--old-key-id`.
Future `rde.v1`
rotations remain a separate manually approved procedure: pass each old key ID
to `inventory`, then positionally pair every old root with the same explicit
key ID in `dry-run` and `apply`.

After active-release validation, the script durably publishes
`activation-commit.json`; this is the irreversible activation commit point.
Before production migration begins, pre-migration recovery may restore the old
application. If data services were switched, it first restores their recorded
tags, recreates PostgreSQL/Redis, and proves health plus `0058`; otherwise it
proves the existing dependencies before restoring the old application. Every
recreated service must bind its previous Compose image reference to exactly one
valid rollback-map SHA256 and prove the running container `.Image` matches it;
an application mismatch is re-fenced and an incomplete recovery retains the
deployment lock. The complete protected runtime env continues to reach Compose
and backend containers by file, while only explicitly reviewed keys may be
imported into the root host shell. Once
production migration begins and before activation commits, do not downgrade or
restart old code. Restore the matched whole `0058` database backup, old
application revision, original external env snapshot, and the two old roots
from the digest-bound maintenance snapshot together. Failure of
either independently transactional `apply`, or of any later pre-activation
step, requires that whole recovery point; retaining only one newly encrypted
domain is forbidden. A database-only, code-only, env-only, or root-only
rollback is forbidden.

After activation commits, cleanup, private/global evidence, or unlock failure keeps the
healthy new runtime and pointer. It must not stop writers, restore tags, or
attempt destructive rollback. Retain or reacquire `.deploy-lock` and record
`activation_committed_terminalization_incomplete`, then repair terminalization.
Terminal success order is fixed: clean rollback tags/maps, publish the final
mode-`0600` `cutover-result.json` with the persistent receipt digest, publish
the global activation receipt bound to activation/result digests, release
`.deploy-lock`, then mark complete. Success evidence must not coexist with
unresolved failure evidence.
Normal runtime has no legacy or dual-read path. It accepts only active `rde.v1`
and `sse.v1` envelopes and rejects raw Fernet. The Runtime Data tool supports a
separately approved future `rde.v1` rotation. The Service Settings tool supports
only the first raw-Fernet to `sse.v1` cutover; a later `sse.v1` rotation requires
a new approved old-key-ID contract.

If an exact green `production` revision changes only public static legal/policy
content under `site/terms/*`, an operator may manually run the static terms fast
path without rebuilding Docker images, running migrations, refreshing
providers, or restarting runtime services. The fast path must use a unique
root-owned mode-`0600` protected upload, acquire the normal remote
`.deploy-lock`, freeze and validate one direct managed `release-*` target, and
perform the terms replacement transactionally through `terms.previous`. Public
terms and liveness checks run before transaction cleanup and proved unlock. A
pre-commit failure restores the prior terms state and writes private failure
evidence; any incomplete recovery, cleanup, or unlock returns nonzero and
retains the shared lock and evidence for operator repair. This exception is
limited to static terms content; proxy, compose, application, runtime,
provider, database, and workflow changes must use the full production deploy
path.

## Emergency Rule

If production is broken and SSH hotfixing is unavoidable:

1. record the command or file changed;
2. verify `https://cloud.npc.ink/health/live`;
3. backport the fix to Git before the next deploy;
4. note whether rollback is still possible from the previous release.

## Upgrade Trigger

Move from this lightweight policy to enforced GitHub branch protection and
environment approval when any of these become true:

- production has meaningful external users;
- more than one person can merge or deploy;
- paid customers or credits are active;
- production incidents would create material support or trust cost.
