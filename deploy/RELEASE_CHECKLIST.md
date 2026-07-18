# Cloud Release Checklist

> Status: canonical release gate
>
> Updated: 2026-07-10
>
> Scope: formal Cloud release execution, production environment verification,
> smoke, and rollback readiness

## 1. Purpose

This checklist is the final gate before formally releasing Npcink AI Cloud.

It is intentionally split into:

- repo ready: repository code, scripts, and local validation are landed
- env required: production secrets, URLs, trusted hosts/TLS, worker cadence, OTLP, and provider credentials are configured on the release host
- service settings required: Portal public URL, QQ login when used, and SMTP are configured in `/admin/service-settings`
- operator required: backup/rollback, cadence, heartbeat, trace, token rotation, and log inspection procedures are confirmed by the release operator
- smoke required: `deploy/release-smoke.sh`, real mailbox login, and one real signed hosted runtime request pass on the release host

Cloud may be promoted for controlled production validation with explicit
operator approval. It may be declared generally available only when every
`Required` item below is complete.

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
| OTLP sink | operator required | release operator | a fresh Cloud trace is queryable in the configured production sink |
| 24-hour observation | operator required | release operator | health, workers, cadence, SMTP, callback, and runtime remain stable for 24 hours |
| QQ login, when enabled | service settings required | release operator | real QQ login and `/open/auth/qq/callback` pass; otherwise QQ remains disabled |

## 3. Required Production Environment Checks

All items in this section are `Required`.

### 3.1 Secrets

- [x] `NPCINK_CLOUD_INTERNAL_AUTH_TOKEN` is set to a production value
- [x] `NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN` is set to a separate production value
- [x] `NPCINK_CLOUD_ADMIN_SESSION_SECRET` is set to a production value
- [x] `NPCINK_CLOUD_SERVICE_SETTINGS_SECRET` is set to a stable, dedicated production value and is preserved across deploys and admin-session key rotation
- [ ] `NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET` is set to a stable, dedicated production value and is not reused by admin sessions, Portal JWT, internal auth, bootstrap, or service-settings encryption
- [ ] `NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID` identifies that deployed key without containing secret material
- [ ] the runtime-data encryption secret and key ID are present for `api`, `worker`, `callback-worker`, and `ops-worker`, and are absent from `frontend`
- [ ] Provider Connection credentials have been re-imported or re-saved with the dedicated service-settings key before runtime traffic is restored; ciphertext created by the retired admin/Portal/internal key selection is intentionally unreadable after this cutover
- [x] retired `OPS_*` and runtime `OPENAI_COMPATIBLE_*` names are absent from `.env.deploy`
- [x] QQ Open Platform uses only `/open/auth/qq/callback`
- [x] stored service credentials decrypt after restart without admin-session, Portal JWT, or internal-token fallback
- [x] `NPCINK_CLOUD_PORTAL_JWT_SECRET` is set to a production value
- [x] at least one real hosted-runtime provider credential is configured for the release host
- [x] `NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN` is not equal to `NPCINK_CLOUD_INTERNAL_AUTH_TOKEN`
- [x] browser origin allowlist and trusted host settings match the public release origin

### 3.2 Public Base URLs

- [x] local development entry remains `http://127.0.0.1:8010/` and is not used
  as a production public URL
- [x] production `.env.deploy` sets `NPCINK_CLOUD_BASE_URL=https://cloud.npc.ink`
- [x] `NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST=https://cloud.npc.ink`
- [x] `NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST=cloud.npc.ink` is the public-host
  baseline; production also includes required internal container/loopback hosts
- [x] `/admin/service-settings` Portal public URL matches the real public portal URL
- [x] public reverse proxy and TLS are already valid for the release host

### 3.3 Portal Login And Email Service Settings

- [x] `/admin/service-settings` Portal public URL is saved
- [x] `/admin/service-settings` QQ login is configured and tested when QQ login is enabled; QQ is currently disabled
- [x] `/admin/service-settings` SMTP host, port, TLS mode, sender email, and sender name are configured
- [x] `/admin/service-settings` SMTP username and write-only password are configured if required by provider
- [x] the stored SMTP and payment secrets remain readable after an API restart with the same `NPCINK_CLOUD_SERVICE_SETTINGS_SECRET`
- [x] one real mailbox received three consecutive messages from production SMTP

### 3.4 Production Guardrails

- [x] `NPCINK_CLOUD_ALLOW_DEV_ADMIN_INTERNAL_TOKEN_FALLBACK=false`
- [x] no development-code seam is relied on for release verification
- [x] no stub-only login path is used during production smoke
- [x] `ops-worker` is deployed and running with the intended cadence intervals
- [x] `callback-worker` is deployed and running for terminal callback delivery
- [x] `NPCINK_CLOUD_API_WORKERS=1` matches the current 2 CPU / 1.8GiB RAM host budget
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
- [x] OTLP export target is explicit for the release host:
  - `NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT`
  - `NPCINK_CLOUD_OTEL_TRACE_SINK_OTLP_ENDPOINT`
  - `NPCINK_CLOUD_OTEL_TRACE_QUERY_URL`

## 4. Database Readiness

All items in this section are `Required`.

- [x] target database backup exists and restore path is known
- [ ] the pre-cutover custom-format backup has a recorded checksum, restrictive permissions, and a successful restore verification against a separate database
- [ ] the pre-cutover code revision and old runtime-data decryption key material are recoverable together with that backup
- [x] migration state is confirmed on the release target
- [ ] schema drift has been checked on the target host
- [x] rollback plan for the database has been written down

Operator note:

- if the target database was originally bootstrapped outside Alembic control, verify migration baseline explicitly before release
- the 2026-07-10 production restore drill passed against migration `0057`; see
  `docs/production-backup-restore-drill-2026-07-10.md`

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
  - `NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN`
  - `NPCINK_CLOUD_RELEASE_MEMBER_EMAIL`
  - `NPCINK_CLOUD_PORTAL_LOGIN_CODE`
  - `NPCINK_CLOUD_RELEASE_SITE_ID`
  - `NPCINK_CLOUD_RELEASE_KEY_ID`
  - `NPCINK_CLOUD_RELEASE_KEY_SECRET`
- after a successful `production` deploy, confirm the `Post-production smoke`
  job passed. It always runs the public small-customer preflight and runs formal
  release smoke automatically when the secrets above are configured;
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
- [ ] `POST /admin/auth/bootstrap` succeeds in the formal release smoke with the production admin token
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

- [x] `platform_admin` bootstrap token storage location is defined
- [x] bootstrap token rotation procedure is defined
- [x] internal service token rotation procedure is defined
- [x] session invalidation procedure is defined
- [ ] runtime-data encryption cutover evidence records successful `inventory`, `dry-run`, `apply`, and new-key-only `verify` runs from `python -m app.dev.reencrypt_runtime_data`
- [ ] all four phases ran with `docker compose ... run --rm --no-deps --env-from-file` from the bundle-backed staged release API image, without requiring host application source or Python
- [ ] before the first staged Compose command, `.env.deploy` was copied from the protected shared/current source, installed mode `0600`, and verified without invoking a general deploy helper that switches `current` or starts services
- [ ] the untracked maintenance env was mode `0600` and contained the target encryption secret/key ID plus an explicit old-root environment value
- [ ] the first raw-ciphertext cutover omitted `--old-key-id`; any later `rde.v1` rotation supplies old key IDs to `inventory` and positionally pairs each ID/root in `dry-run` and `apply`
- [ ] `dry-run`/`apply` used only `--old-root-env` variable names, and `apply` recorded the explicit `--confirm-maintenance-window` acknowledgement without logging key values
- [ ] all four writers were stopped during re-encryption and were restarted only after verification
- [ ] temporary old-key material and the maintenance env were removed after the verification and rollback-evidence window; normal runtime has no legacy/dual-read path, while the migration-only tool remains available for controlled rekey
- [ ] the operator understands that normal deploy/secret rotation must not directly rotate `NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET` or its key ID
- [x] operator has checked `GET /internal/service/ops/cadence` and all required cadence tasks are fresh
- [x] operator has checked `GET /internal/service/observability/summary` and worker heartbeats are fresh
- [x] operator has checked provider health freshness and degraded-provider list
- [ ] operator has confirmed traces are queryable in the configured sink
- [x] rollback command path is written down
- [x] `deploy/OPS_PLAYBOOK.md` is the procedure source used for release
- [ ] operator knows where to inspect:
  - API logs
  - proxy logs
  - worker logs
  - SMTP failure symptoms

## 8. Optional But Recommended

- [ ] run `pnpm run check:e2e:deploy-bundle:smoke` before deploy
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
