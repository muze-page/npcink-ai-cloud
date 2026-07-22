# Cloud Release Checklist

> Status: canonical release gate
>
> Updated: 2026-07-22
>
> Scope: formal Cloud release execution, production environment verification,
> smoke, and rollback readiness

## 1. Purpose

This checklist is the final gate before formally releasing Npcink AI Cloud.

It is intentionally split into:

- repo ready: repository code, scripts, and local validation are landed
- env required: production secrets, URLs, trusted external Edge/TLS, worker
  cadence, external OTLP, and provider credentials are configured on the
  release host
- service settings required: Portal public URL, QQ login when used, and SMTP are configured in `/admin/service-settings`
- operator required: backup/rollback, cadence, heartbeat, trace, token rotation, and log inspection procedures are confirmed by the release operator
- smoke required: `deploy/release-smoke.sh`, real mailbox login, and one real signed hosted runtime request pass on the release host

Cloud may be promoted for controlled production validation with explicit
operator approval. It may be declared generally available only when every
`Required` item below is complete.

Current deployment authority is the fresh PostgreSQL 18 contract:

- first deployment must report the explicit non-secret state
  `installation_state=pending`, skip all post-install preflight/smoke, complete
  `/setup`, run the complete-only smoke, WordPress/RDS/observation acceptance,
  and only then run `deploy/first-install-finalize.sh`;
- ordinary deployment must report `installation_state=complete`, pass the
  candidate RDS PostgreSQL 18/TLS/Alembic preflight, and then run the existing
  small-customer preflight and release smoke;
- any section explicitly labelled `Historical` or `non-normative` preserves
  evidence only. Its unchecked boxes are not current release gates and no
  historical activation or backup receipt is consumed by ordinary deployment.

## 2. Current Repository Status

Current repository status is:

- done: single `platform_admin` token login model is landed
- done: hardening scope is frozen in `cloud-hardening-minimum-operations-v1.md`
- done: invite-only Portal `user` email verification-code login is landed
- done: legacy Portal magic-link and OIDC routes are physically removed from active runtime
- done: legacy multi-platform-admin directory routes are removed from active runtime
- done: Portal session is unified on JWT session cookie
- done: formal release smoke script exists
- done: local validation currently passes:
  - `pytest`
  - `pnpm type-check`
  - `pnpm eslint`
  - `python3 -m compileall`
- done: mini dev sync and browser smoke currently pass at the configured mini-dev frontend origin (for example `http://127.0.0.1:8010/`)

Repository conclusion:

- the PC launch candidate is deployed to production;
- repository, production environment, SMTP, signed runtime, worker/cadence,
  dependency security, and database restore evidence are recorded;
- Cloud must not be treated as GA-ready while any remaining `Required` item is
  unchecked.

Current open blockers:

| Blocker | Category | Owner | Verification |
| --- | --- | --- | --- |
| real Alipay transaction | smoke required | release operator | one low-value payment reaches paid state and grants the expected 365-day credits exactly once |
| real WordPress reconnect | smoke required | release operator | one production Addon reconnect issues a fresh key and revokes the previous active key |
| formal release smoke | smoke required | release operator | configure the required GitHub smoke secrets and run the complete `deploy/release-smoke.sh` path without a conditional skip |
| schema drift baseline | operator required | database owner | historical `alembic check` index-name differences are resolved or recorded as reviewed |
| external OTLP sink | operator required | release operator | exporter and query URLs are explicit and a fresh Cloud trace is queryable in the configured production sink |
| 24-hour observation | operator required | release operator | health, workers, cadence, SMTP, callback, and runtime remain stable for 24 hours |
| QQ login, when enabled | service settings required | release operator | real QQ login and `/open/auth/qq/callback` pass; otherwise QQ remains disabled |

## 3. Required Production Environment Checks

All items in this section are `Required`.

### 3.1 Secrets

- [ ] first install generated the internal token, `NPCINK_CLOUD_ADMIN_KEY`, and
  `NPCINK_CLOUD_ADMIN_SESSION_SECRET` under protected shared config; none is an
  `.env.deploy` assignment
- [ ] the generated Service Settings root is canonical padded URL-safe Base64
  that decodes to exactly 32 random bytes
- [ ] `NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID` identifies the Service
  Settings target root without containing secret material
- [ ] `NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET` is a separate canonical
  padded URL-safe Base64 value that decodes to exactly 32 random bytes and is
  not reused by any authentication or Service Settings domain
- [ ] `NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID` identifies the Runtime Data
  target root without containing secret material and differs from the Service
  Settings key ID
- [ ] both target root/key-ID pairs are present for `api`, `worker`,
  `callback-worker`, and `ops-worker`, and all four variables are absent from
  `frontend`

#### Historical PG16 persisted-secret migration evidence (non-normative)

The following item records the retired in-place migration. A fresh PostgreSQL
18 empty initialization has no legacy rows to migrate and does not consume this
evidence.

- [ ] all eight Provider Connection ciphertexts and four Service Setting secret
  entries were migrated losslessly by
  `python -m app.dev.reencrypt_service_secrets`; migration preserved credential
  values without manual entry or a replacement save operation

#### Current first-install secret checks resume

- [x] retired `OPS_*` and runtime `OPENAI_COMPATIBLE_*` names are absent from `.env.deploy`
- [x] QQ Open Platform uses only `/open/auth/qq/callback`
- [ ] stored service credentials use active `sse.v1` envelopes and decrypt after
  restart without raw-Fernet, legacy, dual-read, Admin-session, Portal JWT, or
  internal-token fallback
- [ ] the generated Portal JWT root is protected by `runtime-config.json` mode `0600`
- [x] at least one real hosted-runtime provider credential is configured for the release host
- [ ] the admin-key digest differs from SHA-256 of the projected internal token
- [x] browser origin allowlist and trusted host settings match the public release origin
- [ ] the exact release payload contains no `.env.deploy`; any uploaded env was
  transferred separately through the protected incoming directory
- [ ] the selected release env is
  `${REMOTE_DIR}/.release-state/<release-name>/env.deploy`, both state
  directories are mode `0700`, and the env file is mode `0600`
- [ ] `current` selects code only and its release basename has a matching
  external state directory; no secret-bearing env file exists inside that
  release payload

### 3.2 Public Base URLs

- [x] local development entry remains `http://127.0.0.1:8010/` and is not used
  as a production public URL
- [x] production `.env.deploy` sets `NPCINK_CLOUD_BASE_URL=https://cloud.npc.ink`
- [x] `NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST=https://cloud.npc.ink`
- [x] `NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST=cloud.npc.ink` is the public-host
  baseline; production also includes required internal container/loopback hosts
- [x] `/admin/service-settings` Portal public URL matches the real public portal URL
- [ ] operator-owned external Edge and TLS are valid for the release host
- [ ] Runtime Compose sets `NPCINK_CLOUD_EXTERNAL_EDGE_READY=true`, and
  `NPCINK_CLOUD_DOMAIN_NAME=cloud.npc.ink` exactly matches the HTTPS base URL
- [ ] production deploy and mutating maintenance share
  `production-host-mutation`; `safe-prune` requires its exact confirmation and
  acquires both the remote `.deploy-lock` and the validated shared install lock

#### Historical P1-E06 Edge migration evidence (non-normative)

The detailed binding and certificate-receipt checklist below preserves the
retired Edge/P1-E06 migration evidence. It is not a current PostgreSQL 18 first
install or ordinary-deploy gate.

- [ ] host NGINX references the Certbot live-lineage `fullchain.pem` and
  `privkey.pem` directly; both symlinks resolve to root-owned non-symlink files
  inside their matching `/etc/letsencrypt/archive` lineage, the private-key
  target grants no group/other permissions, and no `/etc/nginx/ssl` copy exists
- [ ] `deploy/bind-domain-to-ssh-host.sh --prepare-only` held the shared remote
  `.deploy-lock`, passed Certbot-lineage, certificate/key, loopback-upstream,
  inner-health, and candidate `nginx -t` checks, restored the exact old NGINX
  files, and did not upload TLS bytes, stop Caddy, restart NGINX, or switch traffic
- [ ] `deploy/bind-domain-to-ssh-host.sh` activation ran as one locked remote
  transaction: it froze old NGINX state and exact project-Caddy IDs, stopped
  those IDs, activated/validated NGINX, and passed loopback HTTPS
- [ ] failure injection proved the binding transaction restores old NGINX and
  restarts/verifies only its exact frozen Caddy IDs; incomplete recovery retains
  rollback evidence and `/opt/npcink-ai-cloud/.deploy-lock`
- [ ] final Edge health was marked committed before lock release; injected
  release failure retained the healthy Edge, lock, and rollback evidence,
  returned nonzero, and did not run a post-commit rollback
- [ ] the first Edge migration kept the enforced order: locked Edge activation,
  install and directly test the persistent hook, enable
  `certbot-renew.timer`, generate/verify fresh evidence, then prepare images
- [ ] a named certificate-renewal owner is recorded, its automatic
  service/timer is enabled with a known next run, and the Alibaba Cloud Linux 3
  EPEL selection is explicitly `certbot-renew.timer`
- [ ] the timer's effective `Unit` resolves to one service whose effective
  `ExecStart` directly invokes the canonical root-owned, non-group/world-writable
  Certbot executable with `renew`; no shell/`env` wrapper, no-op service,
  ignored error, dry-run-only command, hook-disabling flag, or unrelated
  subcommand is accepted
- [ ] `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx` is a root-owned,
  non-symlink, non-group/world-writable executable; direct execution, renewal
  dry run, `nginx -t`, and reload all passed
- [ ] the named PEM leaf and the leaf served by `127.0.0.1:443` both match
  `cloud.npc.ink`, have at least 30 days remaining, and have identical SHA256
  fingerprints
- [ ] readiness parsed the effective `nginx -T` server block, bound the exact
  `ssl_certificate`/`ssl_certificate_key` live-lineage paths and binding digest,
  and proved the named certificate matches the protected private key
- [ ] the exact staged release ran
  `deploy/certificate-renewal-readiness.sh generate` as root with
  `/usr/bin/python3.11`; its root-owned mode-`0600` evidence is no older than
  seven days, binds `renewal_service`, `certbot_real_path`,
  `renewal_exec_start_sha256`, certificate/private-key archive targets, and the
  actual NGINX TLS binding, and `verify` rechecked all of them; at that dated
  snapshot no receipt existed
- [ ] the active env explicitly persists all four values without defaults
  after the initial P1-E06 orchestrator's lock-held handoff; the operator did
  not edit the active env:
  `NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH`,
  `NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH`,
  `NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER`, and
  `NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH`
- [ ] Runtime Compose sets `NPCINK_CLOUD_EXTERNAL_EDGE_READY=true`; for the
  initial P1-E06 cutover this became true only through the orchestrator's
  lock-held exact-five-key handoff
- [ ] `NPCINK_CLOUD_DOMAIN_NAME=cloud.npc.ink` exactly matches the HTTPS
  `NPCINK_CLOUD_BASE_URL` host
- [ ] production deploy and mutating maintenance share
  `production-host-mutation`; `safe-prune` requires its exact confirmation and
  acquires the remote `.deploy-lock` before pruning any image or release

P1-E06 inventory note (2026-07-20): host NGINX was absent, Caddy was still
running, and the readiness flag was absent. This is historical context only;
the unchecked evidence above is not authoritative for current deployment.

### 3.3 Portal Login And Email Service Settings

- [x] `/admin/service-settings` Portal public URL is saved
- [x] `/admin/service-settings` QQ login is configured and tested when QQ login is enabled; QQ is currently disabled
- [x] `/admin/service-settings` SMTP host, port, TLS mode, sender email, and sender name are configured
- [x] `/admin/service-settings` SMTP username and write-only password are configured if required by provider
- [ ] stored SMTP and payment secrets use active `sse.v1` envelopes and remain
  readable after an API restart with the same Service Settings root/key-ID pair
- [x] one real mailbox received three consecutive messages from production SMTP

### 3.4 Production Guardrails

- [ ] the exact release canonical allowlist either no longer contains the three
  governed Python `3.14.6` entries, or the temporary bundle-external
  `npcink.controlled_production_cve_risk_acceptance.v1` receipt and its separate
  SHA-256 file are operator-owned mode `0600`, fresh, unexpired, and bind the
  exact Linux/AMD64 source, bundle, allowlist, passed scan, API receipt, and
  exact finding set; in either case the fresh exact-image scan is green
- [ ] while any governed entry remains, the machine-executable first-install
  gate consumes and validates both external evidence files before remote mkdir,
  upload, deployment lock, image, container, or database mutation; absence,
  partial matches, changed threat intelligence, changed scan evidence, unsafe
  protection, or any binding mismatch fails closed and there is no skip flag
- [ ] the production SSH user is explicit, the exact production commit has a
  completed successful `Cloud CI` run, and either the manually dispatched
  `Deploy Production` workflow received its confirmation and Environment
  approval or the documented temporary first-install trusted-workstation path
  received the exact bundle-bound operator acceptance; no push triggered a
  deployment
- [ ] the deployment emitted exactly one explicit `installation_state` result;
  no HTTP failure or Setup-route response was interpreted as pending
- [ ] a `pending` result skipped every post-install preflight/smoke step and
  produced the root/TTY setup-code, `/setup`, admin-key, complete-only smoke,
  WordPress/RDS/observation, and final acceptance handoff; a `complete` result
  ran the ordinary-deploy post-install gates
- [ ] host release tooling selected `/usr/bin/python3.11`, proved Python
  `>=3.11` before any remote mkdir/upload/lock, and remained separate from the
  Cloud application image's Python `>=3.12` runtime
- [ ] `/opt/npcink-ai-cloud` is uniformly `root:root` and has no managed
  group/world-writable path; `/var/backups/npcink-ai-cloud` and
  `/run/npcink-ai-cloud` are root-owned mode `0700`
- [ ] the production Environment has a pinned `PROD_SSH_KNOWN_HOSTS` entry
  verified through an independent channel; runtime `ssh-keyscan` is not used,
  and SSH/SCP enforce `StrictHostKeyChecking=yes`
- [x] `NPCINK_CLOUD_ALLOW_DEV_ADMIN_INTERNAL_TOKEN_FALLBACK=false`
- [x] no development-code seam is relied on for release verification
- [x] no stub-only login path is used during production smoke
- [x] `ops-worker` is deployed and running with the intended cadence intervals
- [x] `callback-worker` is deployed and running for terminal callback delivery
- [ ] production Compose fixes Gunicorn to exactly one API worker and
  `.env.deploy` contains no `NPCINK_CLOUD_API_WORKERS` override
- [x] `NPCINK_CLOUD_RUNTIME_WORKER_POLL_SECONDS` is set for the release host
- [x] `NPCINK_CLOUD_RUNTIME_CALLBACK_WORKER_POLL_SECONDS` is set for the release host
- [x] `NPCINK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS` is set for the release host
- [x] cadence env is explicitly set for the release host:
  - `NPCINK_CLOUD_OPS_CADENCE_POLL_SECONDS`
  - `NPCINK_CLOUD_RETENTION_CLEANUP_INTERVAL_SECONDS`
  - `NPCINK_CLOUD_USAGE_ROLLUP_INTERVAL_SECONDS`
  - `NPCINK_CLOUD_ROUTER_DIAGNOSTICS_INTERVAL_SECONDS`
  - `NPCINK_CLOUD_LATENCY_PROBE_INTERVAL_SECONDS`
  - `NPCINK_CLOUD_ALERT_PROVIDER_DEGRADATION_INTERVAL_SECONDS`
  - `NPCINK_CLOUD_PROVIDER_HEALTH_SCAN_INTERVAL_SECONDS`
- [ ] previous and new env state resolve the same Compose project name, and the
  equality check plus actual old-writer container-label check passed before any
  image or container mutation
- [ ] if `--skip-frontend-image` was selected, exactly one running old frontend
  was proven before mutation; the option was not used for a first deploy
- [ ] ordinary production deployment proved an existing managed `current` release;
  no missing-pointer state was treated as an implicit host bootstrap
- [ ] before image mutation, protected state proved `complete`,
  `database_contract=pg18_empty_initialization.v1`, and the exact
  `runtime-config.json` SHA-256
- [ ] after exact images loaded and before old writers stopped, the candidate
  API proved private RDS resolution, TLS `verify-full`, PostgreSQL major 18,
  and exactly one known Alembic revision at the candidate head or on its
  ancestor chain; after migration it proved the exact sole candidate head
- [ ] `.env.deploy` contained no database credential, database URL, runtime
  root secret, or exact-bundle smoke override; these values remained in the
  protected structured configuration where applicable
- [ ] post-load verification published only the fixed
  `.release-state/<release-name>/target-daemon-images.json` map; both state
  directories were owner-controlled non-symlink mode-`0700` directories, the
  map was an owner-controlled non-symlink regular file with mode `0600`, and
  both read and write rejected maps larger than 256 KiB. Its bundle binding
  matched the manifest and checksum hashes, source revision, image platform,
  release name, and canonical resolved release path; malformed, oversized,
  copied, tampered, or differently bound maps were rejected rather than
  overwritten
- [ ] `prepare-only` ran the full pre-load and post-load payload verification
  before publishing the map. Every later phase remained in the same deployment
  lock, proved that the exact release root was operator-owned and not
  group/world writable, relied on the no-direct-server-code-edit policy, and
  revalidated map binding, current governed tags, and candidate containers;
  any unprovable release-root trust stopped the cutover and required a fresh
  `prepare-only` plus full verifier run
- [ ] the observed cutover order was `state/digest -> prepare images ->
  candidate RDS PG18/TLS/Alembic preflight -> stop old app/write services ->
  Redis -> RDS migration/refresh -> pointer -> API -> workers ->
  release-specific worker proof -> generic operational-ready -> traffic`
- [ ] each `data-only`, `api-only`, `workers-only`, and `traffic-only` batch
  froze all required target-daemon IDs and pinned its Compose image seams,
  created the complete batch with
  `up --no-start --pull never --no-build --no-deps --force-recreate`, captured
  exactly one stopped `created`/zero-restart container ID per service, and
  re-proved every candidate image plus governed tag only after the whole batch
  existed. Only a fully proved batch was started by its captured IDs, and the
  post-start gate proved those same IDs were running the same images before
  health or readiness checks
- [ ] migration and provider refresh pinned the profiled `release-one-off` API
  service to the target-daemon map, created exactly one stopped candidate with
  `up --no-start --pull never --no-build --no-deps --force-recreate`, proved its
  `.Image` and the tag before starting the captured container ID, rechecked that
  running identity before `docker exec -i`, removed the proof container, and
  verified signal cleanup plus the cross-release private lock; incomplete
  cleanup retained that lock for operator recovery, and Runtime Compose used
  `pull_policy: never`
- [ ] after worker startup, exactly one `worker`, `callback-worker`, and
  `ops-worker` container stayed running/non-restarting with zero restarts and
  stable IDs, and all three heartbeats were newer than the recorded cutoff
- [ ] the operator has verified that any failure after migration starts remains
  fail-closed and never auto-starts the old application
- [ ] a recovery with incomplete stopped-service, pointer, or failure-marker
  evidence retains `.deploy-lock` for manual recovery
- [ ] recovery used an isolated process environment so new env values could not
  override the matched release inputs; RDS recovery used the matching restore
  point and protected structured configuration, never old code against a
  migrated database
- [ ] protected structured configuration remained available read-only to the
  backend, while the root host shell imported only the reviewed exact env-key
  allowlist
- [ ] successful deployment retained the per-release external env state and
  removed the temporary rollback-image map and private rollback tags
- [ ] post-activation incoming/tag/map/marker/unlock failure returned nonzero,
  kept the healthy new `current`, retained the rollback map and `.deploy-lock`,
  wrote `post_commit_cleanup_incomplete`, and never restarted the old runtime
- [ ] the Cloud bundle exposes no public `80/443`; external Edge traffic reaches
  only the loopback NGINX ingress
- [ ] the external Edge replaces inbound `X-Real-IP`, `X-Forwarded-For`,
  `X-Forwarded-Proto`, `X-Forwarded-Host`, and `X-Forwarded-Port` values
- [ ] NGINX trusts real-client headers only from the gateway frozen in the
  protected per-release runtime network state, sets upstream
  `X-Forwarded-For` from `$remote_addr`, and Gunicorn trusts only the proxy IPv4
  address frozen in that same state
- [ ] the loader reported
  `[ok] Retired bundle services are absent: caddy jaeger otel-collector` before
  public health verification
- [ ] no current release-project container remains for `caddy`, `jaeger`, or
  `otel-collector`
- [ ] external OTLP release evidence is explicit for the release host:
  - `NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT`
  - `NPCINK_CLOUD_OTEL_TRACE_QUERY_URL`
- [ ] a fresh Cloud trace exported through that endpoint is queryable through
  the configured query URL

## 4. Database Readiness

All items in this section are `Required`.

- [ ] Alibaba RDS PostgreSQL major version is exactly 18, uses only the approved
  private endpoint, and resolves only to approved private addresses
- [ ] the application account and empty database exist with only the required
  DDL, index, sequence, and transaction permissions
- [ ] the authoritative RDS CA is stored as protected `rds-ca.pem`; the real
  connection passed TLS `verify-full`
- [ ] the local/CI PG18 proof passed the complete empty Alembic upgrade,
  idempotent replay, JSONB, timestamptz, partial index, `ON CONFLICT`,
  `SKIP LOCKED`, and queue-fencing semantics; this proof is not accepted as RDS
  TLS evidence
- [ ] protected `install-state.json` and `runtime-config.json` carry the
  current `pg18_empty_initialization.v1` contract and matching SHA-256
- [ ] the candidate-image RDS/TLS/PG18/Alembic preflight passed before old
  writers stopped
- [ ] an RDS backup exists, its restore path is known, and a restore drill to a
  separate validation target passed
- [ ] the Basic Edition instance is used only for development/validation and is
  scheduled to upgrade to high availability before the first real user, paid
  workload, or irreplaceable data
- [ ] migration state and schema drift are confirmed on the release target
- [ ] rollback identifies a matched release, protected runtime configuration,
  and RDS restore point; no automatic old-code connection to a migrated schema
  is allowed

## 5. Formal Release Smoke

All items in this section are `Required`.

Prepare a local, untracked smoke env file:

```bash
mkdir -p .tmp
cp deploy/release-smoke.env.example .tmp/release-smoke.env
chmod 600 .tmp/release-smoke.env
```

Fill `.tmp/release-smoke.env` from the production secret store and real mailbox.
Do not commit the filled file.

Preferred GitHub Actions path:

- add the same values to GitHub Actions secrets before the formal release:
  - `NPCINK_CLOUD_INTERNAL_AUTH_TOKEN`
  - `NPCINK_CLOUD_ADMIN_KEY`
  - `NPCINK_CLOUD_RELEASE_MEMBER_EMAIL`
  - `NPCINK_CLOUD_PORTAL_LOGIN_CODE`
  - `NPCINK_CLOUD_RELEASE_SITE_ID`
  - `NPCINK_CLOUD_RELEASE_KEY_ID`
  - `NPCINK_CLOUD_RELEASE_KEY_SECRET`
- after a successful manually dispatched `Deploy Production` run, first inspect
  its explicit `installation_state` output. For `pending`, confirm both
  post-install steps were skipped, then follow the Setup, independent smoke,
  WordPress/RDS/observation, and finalization handoff. For `complete`, confirm
  `Small-customer preflight` passed and optional
  `Formal release smoke` either passed or explicitly reported that the required
  secrets were not configured;
- manually run the `Release Smoke` workflow from the `production` branch;
- keep `require_alipay_enabled=true` for a paid trial release;
- treat a green `Release Smoke` run as the formal smoke evidence for the items
  below, but not as a replacement for the real WordPress plugin runtime flow in
  section 6.

Before running the formal smoke, run the small-customer trial preflight:

```bash
NPCINK_CLOUD_ENV_FILE=.tmp/release-smoke.env \
  bash deploy/small-customer-trial-preflight.sh \
    --base-url https://cloud.npc.ink \
    --require-smoke-env \
    --require-alipay-enabled
```

Then run the formal smoke:

```bash
NPCINK_CLOUD_ENV_FILE=.tmp/release-smoke.env \
  bash deploy/release-smoke.sh \
    --base-url https://cloud.npc.ink
```

Required outcomes:

- [x] `GET /health/live` returns `200`
- [x] `GET /health/ready` with internal auth returns `200`
- [x] `GET /health/operational-ready` with internal auth returns `200`
- [x] `GET /internal/service/observability/summary` with internal auth returns `200`
- [x] `GET /` loads
- [x] `GET /portal/login` loads
- [ ] `POST /portal/v1/auth/code/request` succeeds in the formal release smoke
- [ ] `POST /portal/v1/auth/code/verify` succeeds with a real login code in the formal release smoke
- [ ] `GET /portal/v1/session` succeeds after formal smoke login
- [x] `GET /admin/login` loads
- [ ] `POST /admin/auth/login` succeeds in the formal release smoke with the operator admin key
- [ ] `GET /admin/session` succeeds after formal smoke admin login
- [x] signed `GET /v1/catalog/models` returns the model catalog
- [x] signed `POST /v1/runtime/execute` succeeds against the production provider configuration
- [x] signed `GET /v1/runs/{run_id}` returns the same run id
- [x] signed `GET /v1/runs/{run_id}/result` exposes the runtime result
- [x] signed `GET /v1/stats/profiles/{profile_id}` returns profile stats
- [x] signed `GET /v1/usage/summary` exposes the rolling usage counters
- [ ] the complete `deploy/release-smoke.sh` path runs with all required smoke credentials; the signed runtime subset passed manually

Small-customer paid trial preflight is incomplete unless:

- [ ] `deploy/small-customer-trial-preflight.sh --require-smoke-env --require-alipay-enabled` passes with the formal smoke env
- [x] the `Post-production smoke` GitHub Actions job passes after a production deploy
- [x] `/open/payments/alipay/return` redirects to `/portal/billing?payment_return=alipay...`
- [x] `/open/payments/alipay/notify` rejects an unsigned or empty callback
- [ ] the filled smoke env file remains outside Git and has restricted local permissions

## 6. Plugin and Runtime Verification

This section is `Required` for first release or runtime/auth changes.

- [ ] connect or reconnect one real site from the WordPress Cloud addon so Cloud automatically issues a fresh customer-facing API key
- [ ] confirm the addon stores the issued key and the previous active site key is revoked
- [ ] plugin connection test passes
- [ ] plugin service status stays read-only and does not expose Cloud write controls
- [ ] plugin provider/runtime evidence is read-only service detail, not a second control plane
- [x] one real signed runtime request succeeds
- [x] the runtime request does not fail with `runtime.provider_not_configured`
- [ ] site usage / key / portal state remain coherent after the runtime call

## 7. Operational Sign-Off

Post-release timing evidence:

- [x] GitHub Actions release timing was captured with `pnpm run release:timing -- 29084936244`
- [x] backend, frontend, deploy, overall release, and smoke durations were recorded; the production environment approval was confirmed
- [x] no unexpected release-time regression was observed

All items in this section are `Required`.

- [x] `platform_admin` admin-key digest storage location is defined
- [x] admin-key and admin-session rotation procedure is defined
- [x] internal service token rotation procedure is defined
- [x] session invalidation procedure is defined
- [ ] the exact Linux/AMD64 bundle was staged with
  `deploy/deploy-to-ssh-host.sh --stage-only --skip-bundle-build`, without
  `--env-file` or `NPCINK_CLOUD_ENV_FILE`, and its only accepted result was
  `staged_release=/absolute/release-path`; `/usr/bin/python3.11` was selected
  through `--host-python` or `NPCINK_CLOUD_DEPLOY_HOST_PYTHON`
- [ ] stage-only uploaded, archive-checked, safely extracted, and pre-load
  verified the bundle without resolving/changing `current`, creating release
  state, calling Docker, loading images, mutating containers, migrating,
  refreshing, seeding, smoking, or starting traffic; the remote argument
  envelope contained only mode/root/release/incoming/host-Python values and
  early failure left no incoming object, partial release, or lock
### Historical PG16/P1-E06 evidence (non-normative)

The following unchecked boxes are preserved as an audit record of the retired
cutover. They are not current release gates, do not require an activation
receipt, and must not reopen a compatibility path after fresh PostgreSQL 18
initialization.

- [ ] the independent P1-E06 Edge topology and certificate evidence were closed
  before the orchestrator: host NGINX active, `nginx -t` green, exact-host
  loopback HTTPS green, retired Caddy stopped, and explicit renewal
  owner/timer/persistent-hook values, direct hook, dry run, reload, served-leaf
  fingerprint match, and 30-day expiry gates passed; the active env was not
  edited manually; the orchestrator's first lock-held preflight durably synced
  its recovery anchors, published only the exact five Edge keys, and verified
  fresh `npcink_cloud_certificate_renewal_readiness.v1` evidence before image
  snapshot/tag/load or database mutation; any failed regeneration had already
  invalidated and fsynced the prior receipt;
  stage-only upload/verification was allowed to precede this gate
- [ ] the separate root-owned mode-`0600` Edge-readiness env stayed outside the
  release tree and contained exactly the five reviewed non-secret keys; under
  `.deploy-lock` the orchestrator froze it, snapshotted the original current
  env as `.current-env.snapshot`, changed no other key, and wrote value-free
  `p1_e06_edge_readiness_env_handoff.v1` digest evidence; handled
  pre-migration failures and catchable `HUP`/`INT`/`TERM` signals restored the
  exact original bytes, while any `SIGKILL`/host-power-loss recovery used the
  retained snapshot and deploy lock instead of assuming an automatic rollback
- [ ] the untracked maintenance env stayed outside the release tree, was mode
  `0600`, and contained exactly six keys: two target root/key-ID pairs plus the
  Runtime Data and Service Settings old-root variables; both target roots were
  canonical padded URL-safe Base64 encoding exactly 32 random bytes. The exact
  old-root names were `NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET` and
  `NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET`; the lock-held six-key
  snapshot was removed on pre-migration failure/success but retained with its
  SHA-256 on any post-migration/pre-activation failure
- [ ] `deploy/runtime-data-encryption-cutover.sh` ran once in the foreground
  with `/usr/bin/python3.11`, the exact staged path, `--edge-readiness-env`,
  backup path, previously absent receipt path, and all three required
  acknowledgements
- [ ] the orchestrator used only the governed `remote-load-and-up.sh`
  `prepare-only` mode before stopping public services and fencing `api`,
  `worker`, `callback-worker`, and `ops-worker`
- [ ] the process paused after publishing the fresh backup/checksum and
  mode-`0600` handoff marker; no same-host copy or pre-created receipt was
  accepted as off-host evidence
- [ ] the same process accepted the operator's receipt, completed the
  independent PostgreSQL 16 restore/rehearsal, then recorded successful
  production `inventory`, `dry-run`, `apply`, and new-key-only `verify` phases
  from both `python -m app.dev.reencrypt_runtime_data` and
  `python -m app.dev.reencrypt_service_secrets`; evidence proved Runtime Data
  `18 = 17 + 1`, Service Settings `12 = 8 + 4`, and `30` total rows
- [ ] the canonical-JSON row-identifier SHA-256 values matched the reviewed
  Runtime Data `675cce444dbbf801bc8ab7fb35b717888c878e062097e5fb7f2f5f110e5a764c`
  and Service Settings
  `e5010d2b0a2afe22b7729c4c2395c91001a078e282abee87f03a5f0289aa0bf6`
  sets; no count-preserving identity substitution was accepted
- [ ] after receipt/restore rehearsal and before production migration, the
  orchestrator switched PostgreSQL and Redis to the exact target image IDs and
  proved both healthy plus PostgreSQL still at `20260710_0058`
- [ ] every production/rehearsal API one-off used the governed
  `release-one-off` stopped candidate: Compose `up --no-start --pull never
  --no-build --no-deps --force-recreate`, exact image/never-started proof,
  start of the captured ID, then `docker exec -i --env VARIABLE_NAME` with
  names only; no secret value argument or env-file run option was used, and
  Runtime Compose `pull_policy: never` plus image-ID proof bound the exact image
- [ ] the first raw-ciphertext cutover omitted `--old-key-id`; any later
  `rde.v1` rotation is a separate approved procedure that supplies old key IDs
  to `inventory` and positionally pairs each ID/root in `dry-run` and `apply`
- [ ] `dry-run`/`apply` used only `--old-root-env` variable names, and `apply`
  recorded the explicit `--confirm-maintenance-window` acknowledgement without
  logging key values; each tool received only its matching old root, while
  inventory and new-key-only `verify` received neither old root
- [ ] Runtime Data and Service Settings `apply` each completed in its own
  database transaction, and the operator understands that failure of either
  apply or any later pre-activation step requires the whole database, old
  release/external env, and both old roots to be restored together
- [ ] after migration started, every failure path re-stopped and proved zero
  running writer containers by managed labels and old/new writer image ancestry
- [ ] all public/write services remained stopped until new-key-only verification;
  API and all three workers then passed release-generation readiness before
  traffic returned
- [ ] the target release's external env state contains both new root/key-ID
  pairs while the prior release's external env remains matched to the old
  backup/code/two-root recovery point
- [ ] after active validation, `activation-commit.json` was durably published as
  the irreversible commit point; only then were rollback tags/maps cleaned,
  mode-`0600` `cutover-result.json` published with the persistent receipt digest,
  the global activation receipt published with activation/result digests, and
  finally `.deploy-lock` removed before the operation was marked complete
- [ ] the operator verified that failures before activation commit use the
  phase-specific rollback contract, while post-commit terminalization failure
  keeps the healthy new runtime/pointer, does not stop writers or restore tags,
  and records `activation_committed_terminalization_incomplete` while retaining
  or reacquiring `.deploy-lock`
- [ ] the operator understands the restore boundary: before production
  migration, restore recorded PostgreSQL/Redis tags and dependencies first if
  data images switched, prove health and unchanged `0058`, then resume old code;
  after migration starts, restore the whole `0058` dump plus old release,
  original external env from `.current-env.snapshot`, and both old roots
  from the digest-bound `.maintenance-env.snapshot` together, never Alembic
  downgrade or partial rollback
- [ ] temporary old-root material and the maintenance env were removed after
  the rollback-evidence window; normal runtime has no legacy/dual-read path,
  accepts only active `rde.v1` and `sse.v1` envelopes, and rejects raw Fernet
- [ ] the operator understands that normal deploy/secret rotation must not
  directly rotate either the Service Settings or Runtime Data root/key-ID pair

### Current operational checks

- [x] operator has checked `GET /internal/service/ops/cadence` and all required cadence tasks are fresh
- [x] operator has checked `GET /internal/service/observability/summary` and worker heartbeats are fresh
- [ ] operator has retained the exact worker cutoff and evidence that each new
  heartbeat is newer than it; generic freshness alone is not release-generation
  proof
- [x] operator has checked provider health freshness and degraded-provider list
- [ ] operator has confirmed traces are queryable in the configured sink
- [ ] operator has retained the previous exact bundle, database recovery point,
  and prior Edge route for the migration rollback window
- [ ] operator understands rollback restores one matched prior bundle/Edge path
  and must not run retired Caddy beside the new NGINX topology
- [x] rollback command path is written down
- [x] `deploy/OPS_PLAYBOOK.md` is the procedure source used for release
- [ ] operator knows where to inspect:
  - API logs
  - proxy logs
  - worker logs
  - SMTP failure symptoms

## 8. Optional But Recommended

- [ ] run `pnpm run check:e2e:deploy-bundle:smoke` before deploy; its loopback
  plain-HTTP path is a local artifact-replay exception, not a production origin
- [ ] run remote portal smoke for a real invited user admin after deploy
- [ ] verify one non-empty commercial/admin page:
  - `/admin/plans`
  - `/admin/sites/<site_id>`
  - `/portal/billing`

## 9. GA Release Decision

General availability may proceed only if:

- every `Required` checkbox is complete
- release smoke is green
- database backup and rollback are confirmed
- one real Portal mailbox and one real plugin runtime flow have both been verified

If any `Required` item is incomplete, keep the deployment in controlled
production validation and do not declare general availability.
