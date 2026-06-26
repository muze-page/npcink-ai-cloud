# Internal Alpha Baseline - 2026-05-28

Status: completed
Scope: current branch and validation baseline

## Workspace State

Current branch:

- `master...origin/master`

Intentional documentation changes:

- `README.md`
- `docs/internal-alpha-execution-plan.md`
- `docs/internal-alpha-baseline-2026-05-28.md`

Intentional local validation changes:

- `package.json`
- `Makefile`
- `scripts/check-cloud-perimeter.sh`

Generated local artifacts:

- `frontend/test-results/.last-run.json`

Resolution:

- `frontend/test-results/` is ignored in `frontend/.gitignore`.
- `frontend/playwright-report/` is also ignored because it is the paired
  Playwright report output directory.
- Docker-backed deterministic pytest scripts clear OpenAI-compatible provider
  API key environment variables so `.env.local` can hold real local runtime
  smoke credentials without turning baseline tests into live provider tests.

## Validation Results

Commands run from the repository root:

```bash
pnpm run check:fast
pnpm run check:seam
pnpm run frontend:type-check
pnpm run frontend:lint
pnpm run smoke:local-alpha
pnpm run drill:provider-failure
pnpm run drill:callback-failure
pnpm run drill:auth-failure
```

Additional focused command run from the local WordPress plugin repo:

```bash
php tests/unit/cloud-addon-admin-rest-seams-contracts.php
```

Results:

- `pnpm run check:fast`: passed
  - contract: 37 passed, 2 skipped
  - domain: 61 passed
- `pnpm run check:seam`: passed
  - API: 165 passed
  - perimeter: 9 passed
- `pnpm run frontend:type-check`: passed
- `pnpm run frontend:lint`: passed
- `pnpm run smoke:local-alpha`: passed
- `pnpm run drill:provider-failure`: passed
- `pnpm run drill:callback-failure`: passed
- `pnpm run drill:auth-failure`: passed
- `php tests/unit/cloud-addon-admin-rest-seams-contracts.php`: passed

## Notes

The Docker-backed Python test runs emitted local OTLP export noise:

- `otel-collector` could not be resolved from the test container.
- The exporter eventually timed out while sending span batches.
- The test commands still exited successfully.

Classification:

- `pass`: contract, domain, API, perimeter, frontend type check, frontend lint
- `env/dependency noise`: local OTLP collector endpoint is not available during
  these test runs
- `repo failure`: none found in this baseline
- `e2e baseline drift`: existing `portal-workspace-path` and `admin-operator-path`
  Playwright tests have pre-existing failures unrelated to the current frontend
  polish changes. The mobile viewport tests added in this pass pass. The baseline
  records this drift rather than blocking the runtime/ops hardening step on it.

## Local Alpha Environment Check

Target:

- Cloud base URL: `http://127.0.0.1:8010`
- WordPress site: `https://npcink.local/`
- WordPress Cloud addon: installed and enabled
- Portal login path: `/portal/dev-entry`
- Local debug login origin allowlist:
  `http://127.0.0.1:8010,http://localhost:8010`
- Provider target for real runtime smoke: DeepSeek through the OpenAI-compatible
  adapter

Current results:

- `docker compose -f docker-compose.dev.yml up -d --build`: local Cloud stack
  running with `api`, `frontend`, `worker`, `callback-worker`, `ops-worker`,
  `postgres`, `redis`, and `proxy`.
- `GET /health/live`: passed.
- `GET /health/ready`: passed with the local internal token.
- `GET /health/operational-ready`: passed after adding the local
  `callback-worker` service and seeding provider health.
- WordPress addon save-and-verify: passed against `http://127.0.0.1:8010`.
- WordPress addon entitlement summary: loaded Free/starter entitlement details
  from Cloud.
- Portal dev-entry login: passed and landed on `/portal`.
- Portal site record: bound to `site_npcink_local` and updated with
  `https://npcink.local/`.

Fix applied during the local alpha check:

- The Cloud addon signed requests with `sha256(secret)` as the HMAC key while
  Cloud verifies with the plaintext signing secret. This caused
  `auth.invalid_signature` during addon verification.
- The addon runtime client now signs with the plaintext Cloud API Key secret.
- A focused WordPress contract check was added to prevent signing with the
  stored secret hash.

Historical note:

- Earlier local alpha checks used `NPCINK_CLOUD_OPENAI_BASE_URL` and
  `NPCINK_CLOUD_OPENAI_API_KEY` for a DeepSeek OpenAI-compatible provider.
- As of 2026-06-26, OpenAI-compatible runtime providers are configured through
  `/admin/ai-resources` DB provider connections instead of `.env.local`
  provider keys.
- The deterministic test entrypoints explicitly clear local OpenAI-compatible
  provider API key variables during pytest runs. Real provider verification is
  kept in manual smoke steps, not in the default baseline suite.

DeepSeek real runtime smoke:

- Catalog refresh returned real DeepSeek models, including `deepseek-v4-flash`.
- Provider health scan reported 2 healthy DeepSeek-backed instances.
- Public signed `POST /v1/runtime/execute` completed successfully.
- Runtime result:
  - status: `succeeded`
  - provider_id: `openai` (OpenAI-compatible adapter)
  - model_id: `deepseek-v4-flash`
  - instance_id: `openai-global-deepseek-v4-flash`
  - fallback_used: `false`
  - provider_call_count: `1`

Local alpha smoke rehearsal:

- Script: `pnpm run smoke:local-alpha`.
- Evidence file: `.tmp/local-alpha-smoke/evidence-20260528050113.json`.
  (Latest run evidence is under `.tmp/local-alpha-smoke/`; do not commit.)
- Covered:
  - local WordPress homepage and Cloud addon admin tab
  - Cloud health and operational readiness
  - Portal development login-code path and site binding
  - Admin bootstrap session
  - signed catalog, runtime execute, run result, usage summary, and usage meter
  - observability workers/cadence/provider/runtime queue state
- Current evidence:
  - operational ready: `ok=true`
  - workers: 3 fresh, 0 missing
  - cadence tasks: 6 fresh, 0 non-fresh
  - providers: 2 healthy DeepSeek-backed instances
  - runtime: `deepseek-v4-flash`, `fallback_used=false`, `provider_call_count=1`
  - runtime failures: healthy, 0 recent failed runs, 0 recent provider errors
  - operator guidance: healthy, no primary blocker
  - WordPress addon tab: verified
  - Cloud `/v1/addon/*` projection routes: intentionally absent by contract

Runtime and ops hardening:

- `/internal/service/runtime/diagnostics/summary` now exposes:
  - `failures`: recent failed runs, provider error calls, top error codes, and
    dominant error stage
  - `operator_guidance`: primary blocker, evidence path, and bounded suggested
    actions
- Local alpha smoke evidence now records runtime failure and operator guidance
  summaries in addition to queue/callback/provider health.
- Provider failure drill:
  - Script: `pnpm run drill:provider-failure`
  - Evidence file:
    `.tmp/local-alpha-provider-failure-drill/evidence-20260528053406.json`
  - Uses an isolated temporary database and fake OpenAI-compatible provider.
  - Does not use the real DeepSeek key.
  - Forced error: `provider.auth_invalid`
  - Expected guidance: `primary_reason=provider_failures`,
    `primary_evidence_path=failures.dominant_error`,
    `suggested_action=inspect_provider_credentials_quota_and_health`
- Callback failure drill:
  - Script: `pnpm run drill:callback-failure`
  - Evidence file:
    `.tmp/local-alpha-callback-failure-drill/evidence-20260528062202.json`
  - Uses an isolated temporary database, fake successful provider, registered
    terminal callback metadata, and a failing callback dispatcher.
  - Does not use the real DeepSeek key or call WordPress.
  - Forced error: `runtime.callback_delivery_failed`
  - Expected guidance: `primary_reason=callback_delivery`,
    `primary_evidence_path=callback.pressure_reasons`,
    `suggested_action=inspect_callback_delivery_and_retry_buffer`
- Auth failure drill:
  - Script: `pnpm run drill:auth-failure`
  - Evidence file:
    `.tmp/local-alpha-auth-failure-drill/evidence-20260528071147.json`
  - Uses an isolated temporary database, seeded site/key, and FastAPI TestClient.
  - Does not use the real DeepSeek key or call WordPress.
  - Constructs a `POST /v1/runtime/execute` request with a wrong signing secret.
  - Asserts HTTP `401`, `error_code=auth.invalid_signature`.
  - Verifies runtime guard diagnostics capture the auth reject evidence.

Bounded frontend polish (first pass):

- Portal Usage page now integrates `UsageBarChart` for `today` vs `rolling_24h`
  comparison on requests, tokens, and cost.
- `/portal/usage` data fetching now uses the existing `useRetry` hook for initial
  load, site switch, and error retry with `PortalErrorState`.
- Mobile viewport checks added to `/portal/usage`, `/portal`, and `/admin/sites/{siteId}`.
- No checkout/payment/invoice/seat/self-serve onboarding surfaces added.

## Next Step

The current internal alpha baseline is now refreshed. Remaining work before
release remains in the deferred bucket:

- checkout/payment/invoice/dunning
- full customer commercial front office
- seat lifecycle productization
- GA customer portal and self-serve onboarding
- Cloud-owned skills/MCP/router/prompt/workflow control planes
- heavy orchestration infrastructure
