# Cloud Release Checklist

> Status: canonical release gate
>
> Updated: 2026-06-29
>
> Scope: `cloud/**` formal release execution, production env verification, smoke, rollback readiness

## 1. Purpose

This checklist is the final gate before formally releasing Npcink AI Cloud.

It is intentionally split into:

- repo ready: repository code, scripts, and local validation are landed
- env required: production secrets, URLs, trusted hosts/TLS, worker cadence, OTLP, and provider credentials are configured on the release host
- service settings required: Portal public URL, QQ login when used, and SMTP are configured in `/admin/service-settings`
- operator required: backup/rollback, cadence, heartbeat, trace, token rotation, and log inspection procedures are confirmed by the release operator
- smoke required: `deploy/release-smoke.sh`, real mailbox login, and one real signed hosted runtime request pass on the release host

Cloud may be released only when every `Required` item below is complete.

## 2. Current Repository Status

Current repository status is:

- done: single `platform_admin` token login model is landed
- done: hardening scope is frozen in `cloud-hardening-minimum-operations-v1.md`
- done: invite-only `user_admin` email verification-code login is landed
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

- `repo ready` is the only category currently closed by repository evidence
- `env required`, `operator required`, and `smoke required` remain open until a real release host is verified
- Cloud must not be treated as GA-ready while any `Required` item remains unchecked

Current open blockers:

| Blocker | Category | Owner | Verification |
| --- | --- | --- | --- |
| production secrets | env required | release operator | production secret store contains distinct runtime, admin, session, provider, and Portal secrets |
| TLS / trusted hosts | env required | release operator | public release origin has valid TLS and matches trusted host / browser origin allowlists |
| SMTP real mailbox | service settings required | release operator | production SMTP sends a login code to a real invited mailbox |
| worker heartbeat | operator required | release operator | `/internal/service/observability/summary` shows fresh worker heartbeats |
| OTLP sink | operator required | release operator | trace sink endpoint and query URL are configured and a fresh Cloud trace is queryable |
| DB backup/rollback | operator required | database owner | backup artifact exists and rollback procedure has been written down |
| real signed runtime request | smoke required | release operator | plugin/runtime smoke completes without `runtime.provider_not_configured` |

## 3. Required Production Environment Checks

All items in this section are `Required`.

### 3.1 Secrets

- [ ] `NPCINK_CLOUD_INTERNAL_AUTH_TOKEN` is set to a production value
- [ ] `NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN` is set to a separate production value
- [ ] `NPCINK_CLOUD_ADMIN_SESSION_SECRET` is set to a production value
- [ ] `NPCINK_CLOUD_PORTAL_JWT_SECRET` is set to a production value
- [ ] at least one real hosted-runtime provider credential is configured for the release host
- [ ] `NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN` is not equal to `NPCINK_CLOUD_INTERNAL_AUTH_TOKEN`
- [ ] browser origin allowlist and trusted host settings match the public release origin

### 3.2 Public Base URLs

- [ ] local development entry remains `http://127.0.0.1:8010/` and is not used
  as a production public URL
- [ ] production `.env.deploy` sets `NPCINK_CLOUD_BASE_URL=https://cloud.npc.ink`
- [ ] `NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST=https://cloud.npc.ink`
- [ ] `NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST=cloud.npc.ink`
- [ ] `/admin/service-settings` Portal public URL matches the real public portal URL
- [ ] public reverse proxy and TLS are already valid for the release host

### 3.3 Portal Login And Email Service Settings

- [ ] `/admin/service-settings` Portal public URL is saved
- [ ] `/admin/service-settings` QQ login is configured and tested when QQ login is enabled
- [ ] `/admin/service-settings` SMTP host, port, TLS mode, sender email, and sender name are configured
- [ ] `/admin/service-settings` SMTP username and write-only password are configured if required by provider
- [ ] one real mailbox can receive login codes from production SMTP

### 3.4 Production Guardrails

- [ ] `NPCINK_CLOUD_ALLOW_DEV_ADMIN_INTERNAL_TOKEN_FALLBACK=false`
- [ ] no development-code seam is relied on for release verification
- [ ] no stub-only login path is used during production smoke
- [ ] `ops-worker` is deployed and running with the intended cadence intervals
- [ ] `callback-worker` is deployed and running for terminal callback delivery
- [ ] `NPCINK_CLOUD_API_WORKERS` matches the release host CPU/memory budget
- [ ] `NPCINK_CLOUD_RUNTIME_WORKER_POLL_SECONDS` is set for the release host
- [ ] `NPCINK_CLOUD_RUNTIME_CALLBACK_WORKER_POLL_SECONDS` is set for the release host
- [ ] `NPCINK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS` is set for the release host
- [ ] cadence env is explicitly set for the release host:
  - `NPCINK_CLOUD_OPS_CADENCE_POLL_SECONDS`
  - `NPCINK_CLOUD_RETENTION_CLEANUP_INTERVAL_SECONDS`
  - `NPCINK_CLOUD_USAGE_ROLLUP_INTERVAL_SECONDS`
  - `NPCINK_CLOUD_ROUTER_DIAGNOSTICS_INTERVAL_SECONDS`
  - `NPCINK_CLOUD_LATENCY_PROBE_INTERVAL_SECONDS`
  - `NPCINK_CLOUD_ALERT_PROVIDER_DEGRADATION_INTERVAL_SECONDS`
  - `NPCINK_CLOUD_PROVIDER_HEALTH_SCAN_INTERVAL_SECONDS`
- [ ] OTLP export target is explicit for the release host:
  - `NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT`
  - `NPCINK_CLOUD_OTEL_TRACE_SINK_OTLP_ENDPOINT`
  - `NPCINK_CLOUD_OTEL_TRACE_QUERY_URL`

## 4. Database Readiness

All items in this section are `Required`.

- [ ] target database backup exists and restore path is known
- [ ] migration state is confirmed on the release target
- [ ] schema drift has been checked on the target host
- [ ] rollback plan for the database has been written down

Operator note:

- if the target database was originally bootstrapped outside Alembic control, verify migration baseline explicitly before release

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

- [ ] `GET /health/live` returns `200`
- [ ] `GET /health/ready` with internal auth returns `200`
- [ ] `GET /health/operational-ready` with internal auth returns `200`
- [ ] `GET /internal/service/observability/summary` with internal auth returns `200`
- [ ] `GET /` loads
- [ ] `GET /portal/login` loads
- [ ] `POST /portal/v1/auth/code/request` succeeds
- [ ] `POST /portal/v1/auth/code/verify` succeeds with a real login code
- [ ] `GET /portal/v1/session` succeeds after login
- [ ] `GET /admin/login` loads
- [ ] `POST /admin/auth/bootstrap` succeeds with the production admin token
- [ ] `GET /admin/session` succeeds after admin login
- [ ] signed `GET /v1/catalog/models` returns the model catalog
- [ ] signed `POST /v1/runtime/execute` succeeds against the production provider configuration
- [ ] signed `GET /v1/runs/{run_id}` returns the same run id
- [ ] signed `GET /v1/runs/{run_id}/result` exposes the runtime result
- [ ] signed `GET /v1/stats/profiles/{profile_id}` returns profile stats
- [ ] signed `GET /v1/usage/summary` exposes the rolling usage counters
- [ ] release smoke is incomplete unless signed runtime credentials are provided and the signed runtime path passes

Small-customer paid trial preflight is incomplete unless:

- [ ] `deploy/small-customer-trial-preflight.sh --require-smoke-env --require-alipay-enabled` passes
- [ ] `/open/payments/alipay/return` redirects to `/portal/billing?payment_return=alipay...`
- [ ] `/open/payments/alipay/notify` rejects an unsigned or empty callback
- [ ] the filled smoke env file remains outside Git and has restricted local permissions

## 6. Plugin and Runtime Verification

This section is `Required` for first release or runtime/auth changes.

- [ ] create or rotate a real Cloud API key in Portal
- [ ] save the key into the WordPress Cloud addon
- [ ] plugin connection test passes
- [ ] plugin service status stays read-only and does not expose Cloud write controls
- [ ] plugin provider/runtime evidence is read-only service detail, not a second control plane
- [ ] one real signed runtime request succeeds
- [ ] the runtime request does not fail with `runtime.provider_not_configured`
- [ ] site usage / key / portal state remain coherent after the runtime call

## 7. Operational Sign-Off

All items in this section are `Required`.

- [ ] `platform_admin` bootstrap token storage location is defined
- [ ] bootstrap token rotation procedure is defined
- [ ] internal service token rotation procedure is defined
- [ ] session invalidation procedure is defined
- [ ] operator has checked `GET /internal/service/ops/cadence` and all required cadence tasks are fresh
- [ ] operator has checked `GET /internal/service/observability/summary` and worker heartbeats are fresh
- [ ] operator has checked provider health freshness and degraded-provider list
- [ ] operator has confirmed traces are queryable in the configured sink
- [ ] rollback command path is written down
- [ ] `deploy/OPS_PLAYBOOK.md` is the procedure source used for release
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
  - `/portal/keys?site=<site_id>`

## 9. Release Decision

Release may proceed only if:

- every `Required` checkbox is complete
- release smoke is green
- database backup and rollback are confirmed
- one real Portal mailbox and one real plugin runtime flow have both been verified

If any `Required` item is incomplete, do not cut the release.
