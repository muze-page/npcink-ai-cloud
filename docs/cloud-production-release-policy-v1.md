# Cloud Production Release Policy v1

Status: active lightweight gate.

Purpose: define the low-cost production release rules for the current early
validation phase. This policy is a human/process gate until GitHub branch
protection and environment approval are worth paying for.

## Scope

This policy covers changes that may reach `https://cloud.npc.ink`.

It does not create a second WordPress control plane, approval system, ability
registry, workflow registry, prompt truth, provider secret store, or runtime
policy authority. Cloud remains the hosted runtime/service-plane layer.

## Branch Model

- `master` is the development integration branch.
- `production` is the production release source.
- feature and fix branches merge to `master` first.
- production releases are promoted from `master` to `production`.

Do not directly edit production application code on the server. Server-side
changes are limited to runtime secrets in `.env.deploy` and emergency
break-glass fixes that must be backported to Git immediately.

Branch divergence is expected: `production` records the deployed release while
`master` continues development. A production-only patch must not remain an
unexplained long-term fork. Before the next promotion, classify it as already
equivalent on `master`, forward-port it to `master`, or document why the old
deployment behavior is obsolete. Do not merge the accumulated `production`
history back into `master` merely to make the branch graph look aligned.

## Pre-refactor Production Reconciliation

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

## Required Gates Before `master`

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

## Required Gates Before `production`

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
  runtime allowlist may be present, and runtime-data encryption secrets must
  remain backend-only;
- the release payload contains no `.env.deploy`; each managed release resolves
  its backend environment from
  `${REMOTE_DIR}/.release-state/<release-name>/env.deploy`, with both state
  directories mode `0700` and the env file mode `0600`;
- the old and new Compose project names must match before any image or container
  mutation, and the running old writers' actual Compose labels must match that
  project; an ordinary deploy must not silently rename the project and orphan
  old writers;
- a runtime-data encryption key cutover has count-only inventory/dry-run/apply/
  verify evidence, a checksum-verified and restore-tested backup, and the
  matching old code and old key recovery point.
- before P1-E06 starts, the independent production Edge hard gate proves active
  host NGINX, `nginx -t`, exact-host loopback-resolved HTTPS, stopped retired
  Caddy, and persisted `NPCINK_CLOUD_EXTERNAL_EDGE_READY=true`; it also records
  a certificate-renewal owner, enabled automatic renewal service/timer,
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
  post-commit rollback. The exact
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

## Deployment Rule

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
full deployment is never an implicit host bootstrap: a missing managed
`current` release fails before image mutation. Before the first image load, the
deploy reads the current PostgreSQL Alembic revision through the frozen previous
release. Revision `20260710_0058` always fails and can advance only through the
P1-E06 orchestrator. Formal production dispatch additionally requires the
root-owned global P1-E06 activation receipt, its digest-bound complete
per-release evidence, and a current database revision that is `0068` or a
descendant proven from the staged bundle's Alembic graph. Receipt enforcement
is mandatory for every full deploy and is explicitly pinned by the production
workspace target. Only archive-only staging may omit it.
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

Ordinary migration/provider one-offs use Compose
`run -d --name --no-deps --rm`
only to create an inert proof container. Release tooling compares the current
tag and that container's `.Image` with the bundle-manifest API image ID before
executing the payload through `docker exec -i`, then removes the container.
Signal cleanup is mandatory, with a 15-minute self-termination bound as a
second cleanup path.
Docker Compose v2.27 `run` receives no CLI `--pull` option, and Runtime Compose
sets `pull_policy: never` for every explicit-image service.

`NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET` and
`NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID` are exempt from ordinary
configuration-only rotation. They may change only in a planned maintenance
window. The first raw-ciphertext migration is executed only by
`deploy/runtime-data-encryption-cutover.sh`; it must not be reconstructed as a
manual sequence.

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
three-key maintenance env, stop and fence public plus all four writer services,
publish a fresh custom PostgreSQL backup and checksum, and pause in the same
process for independent off-host acknowledgement. The operator must pull the
backup and checksum with `scp`, verify SHA-256 on independent storage, then
atomically publish a new mode-`0600`
`p1_e06_off_host_backup_receipt.v1` receipt containing the matching checksum.
A same-host copy, pre-created receipt, or acknowledgement without that pull is
not backup evidence. Persist the validated receipt content, source path, and
receipt SHA-256 in `off-host-receipt-verified.json`; terminal evidence carries
that digest.

Only after the receipt may the script perform an independent PostgreSQL 16
restore, rehearse `0058 -> 0068`, and run
`python -m app.dev.reencrypt_runtime_data` count-locked `inventory`, `dry-run`,
`apply`, and new-key-only `verify` phases. Before production migration, it then
switches PostgreSQL and Redis to exact target image IDs and proves both healthy
plus PostgreSQL still at `0058`. Production Docker Compose v2.27 one-off
commands use `run --rm --no-deps -e VARIABLE_NAME`; they must never include a
CLI `--pull`, secret values as arguments, or an env-file run option. Runtime
Compose `pull_policy: never` and exact image-ID proof bind the command to the
staged image. Inventory and new-key-only `verify` receive no old root; only
`dry-run` and `apply` do. The first raw-ciphertext cutover omits `--old-key-id`.
Future `rde.v1`
rotations remain a separate manually approved procedure: pass each old key ID
to `inventory`, then positionally pair every old root with the same explicit
key ID in `dry-run` and `apply`.

After active-release validation, the script durably publishes
`activation-commit.json`; this is the irreversible activation commit point.
Before production migration begins, pre-migration recovery may restore the old
application. If data services were switched, it first restores their recorded
tags, recreates PostgreSQL/Redis, and proves health plus `0058`; otherwise it
proves the existing dependencies before restoring the old application. Once
production migration begins and before activation commits, do not downgrade or
restart old code. Restore the matched whole `0058` database backup, old
application revision, old external env, and old key together; a database-only,
code-only, env-only, or key-only rollback is forbidden.

After activation commits, cleanup, private/global evidence, or unlock failure keeps the
healthy new runtime and pointer. It must not stop writers, restore tags, or
attempt destructive rollback. Retain or reacquire `.deploy-lock` and record
`activation_committed_terminalization_incomplete`, then repair terminalization.
Terminal success order is fixed: clean rollback tags/maps, publish the final
mode-`0600` `cutover-result.json` with the persistent receipt digest, publish
the global activation receipt bound to activation/result digests, release
`.deploy-lock`, then mark complete. Success evidence must not coexist with
unresolved failure evidence.
Normal runtime has no legacy or dual-read path; retain the migration-only tool
for future controlled rekeys.

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
