# Npcink AI Cloud

Hosted Model Runtime for Npcink AI.

Npcink AI Cloud is the runtime enhancement layer for the local Npcink plugin.
It is not a second control plane, a second source of truth, or a SaaS
replacement for the plugin.

## Scope Reminder

Npcink AI Cloud is the runtime enhancement layer for the local Npcink plugin.
It is not a second control plane, a second source of truth, or a SaaS
replacement for the plugin.

Current focus lock:

- main target: prove the user-facing hosted GPT5.5 text loop through the normal
  runtime/toolbox path
- keep only minimum usage, error, and provider evidence needed to support that
  loop
- pause new admin governance pages, dashboards, reports, alert-ranking
  expansion, and broad commercial front-office work until the core AI path is
  proven
- do not add new orchestration infrastructure or move local plugin truth into
  Cloud

Current repository status is a strong-contraction cleanup baseline:
- orchestration, task-packs, prompt/preset advisor, and portal thick features
  have been removed
- admin surface is bounded to accounts, sites, plans, subscriptions, billing
  inspect, provider ops, runtime diagnostics, audit, and commercial decisions
- portal surface is bounded to login, session, site connection, usage,
  entitlements, billing, support, Cloud audit, health, and diagnostics; runtime
  keys are system-managed through the WordPress addon connection exchange
- addon projection/repair surfaces are not part of this baseline; they remain
  deferred to a separate proposal with independent review

## Target Refactor Contracts

These documents are the accepted target contracts for the P0-P5 refactor. They
define the intended destination and acceptance boundaries; they are not evidence
that implementation is complete. Delivery remains WordPress-first through P5,
and other CMS adapters are post-P5 validation work.

- [docs/refactor-master-plan-v1.md](docs/refactor-master-plan-v1.md)
- [docs/decisions/004-wordpress-first-cloud-runtime-refactor.md](docs/decisions/004-wordpress-first-cloud-runtime-refactor.md)
- [docs/multi-platform-connector-boundary-v1.md](docs/multi-platform-connector-boundary-v1.md)
- [docs/media-runtime-boundary-v1.md](docs/media-runtime-boundary-v1.md)
- [docs/cloud-first-install-contract-v1.md](docs/cloud-first-install-contract-v1.md)
- [docs/cloud-hosted-runtime-profiles-v1.md](docs/cloud-hosted-runtime-profiles-v1.md)
- [docs/refactor-deletion-inventory-v1.md](docs/refactor-deletion-inventory-v1.md)
- [docs/p4-portal-admin-surface-inventory-2026-07-16.md](docs/p4-portal-admin-surface-inventory-2026-07-16.md)
- [docs/decisions/016-fail-closed-portal-admin-service-boundaries.md](docs/decisions/016-fail-closed-portal-admin-service-boundaries.md)
- [docs/decisions/018-cloud-hosted-runtime-profile-admin-surface.md](docs/decisions/018-cloud-hosted-runtime-profile-admin-surface.md)
- [docs/decisions/019-dedicated-runtime-data-encryption-domain.md](docs/decisions/019-dedicated-runtime-data-encryption-domain.md)
- [docs/decisions/022-one-time-cloud-install-and-rds-postgresql-18.md](docs/decisions/022-one-time-cloud-install-and-rds-postgresql-18.md)
- [docs/decisions/020-external-tls-single-bundled-nginx.md](docs/decisions/020-external-tls-single-bundled-nginx.md)

Evidence records (not target-contract completion proof):

- [docs/refactor-baseline-2026-07-14.md](docs/refactor-baseline-2026-07-14.md)
- [docs/p5-hardening-release-audit-2026-07-17.md](docs/p5-hardening-release-audit-2026-07-17.md)
- [docs/p5-b1-hosted-profile-contract-cutover-2026-07-17.md](docs/p5-b1-hosted-profile-contract-cutover-2026-07-17.md)
- [docs/p5-b2-security-hardening-2026-07-17.md](docs/p5-b2-security-hardening-2026-07-17.md)
- [docs/p5-b4-runtime-load-soak-closeout-2026-07-19.md](docs/p5-b4-runtime-load-soak-closeout-2026-07-19.md)

Operational references:

- [deploy/OPS_PLAYBOOK.md](deploy/OPS_PLAYBOOK.md)
- [deploy/RELEASE_CHECKLIST.md](deploy/RELEASE_CHECKLIST.md)
- [docs/m4-preview-development-v1.md](docs/m4-preview-development-v1.md)
- [docs/portal-commerce-production-development-history-2026-07-11.md](docs/portal-commerce-production-development-history-2026-07-11.md)
- [deploy/PROJECTION_DRILL_EVIDENCE_2026-04-15.md](deploy/PROJECTION_DRILL_EVIDENCE_2026-04-15.md)
- [docs/internal-alpha-execution-plan.md](docs/internal-alpha-execution-plan.md)
- [docs/internal-alpha-operator-checklist.md](docs/internal-alpha-operator-checklist.md)
- [docs/internal-alpha-onboarding-smoke-runbook.md](docs/internal-alpha-onboarding-smoke-runbook.md)
- [docs/external-trial-capability-note-2026-06-10.md](docs/external-trial-capability-note-2026-06-10.md)
- [docs/external-trial-readiness-checklist-2026-06-10.md](docs/external-trial-readiness-checklist-2026-06-10.md)
- [docs/small-customer-trial-commercial-readiness-v1.md](docs/small-customer-trial-commercial-readiness-v1.md)
- [docs/external-trial-operator-runbook-2026-06-11.md](docs/external-trial-operator-runbook-2026-06-11.md)
- [docs/external-trial-copy-and-log-2026-06-11.md](docs/external-trial-copy-and-log-2026-06-11.md)
- [docs/external-trial-record-magick-ai-local-2026-06-10.md](docs/external-trial-record-magick-ai-local-2026-06-10.md)
- [docs/external-trial-user-briefing-copy-zh-2026-06-10.md](docs/external-trial-user-briefing-copy-zh-2026-06-10.md)
- [docs/external-trial-handoff-summary-2026-06-15.md](docs/external-trial-handoff-summary-2026-06-15.md)
- [docs/nightly-inspection-real-site-operator-trial-2026-06-17.md](docs/nightly-inspection-real-site-operator-trial-2026-06-17.md)
- [docs/nightly-inspection-real-site-trial-record-magick-ai-local-2026-06-17.md](docs/nightly-inspection-real-site-trial-record-magick-ai-local-2026-06-17.md)
- [docs/cloud-adapter-analysis-contract.md](docs/cloud-adapter-analysis-contract.md)
- [docs/cloud-local-integration-and-rebuild-guidance.md](docs/cloud-local-integration-and-rebuild-guidance.md)
- [docs/cloud-ai-data-handling-standard-v1.md](docs/cloud-ai-data-handling-standard-v1.md)
- [docs/cloud-production-release-policy-v1.md](docs/cloud-production-release-policy-v1.md)
- [docs/cloud-content-generation-boundary-v1.md](docs/cloud-content-generation-boundary-v1.md)
- [docs/cloud-admin-information-architecture-v2.md](docs/cloud-admin-information-architecture-v2.md)
- [docs/cloud-admin-site-knowledge-development-summary-2026-07-14.md](docs/cloud-admin-site-knowledge-development-summary-2026-07-14.md)
- [docs/decisions/002-cloud-admin-task-oriented-information-architecture.md](docs/decisions/002-cloud-admin-task-oriented-information-architecture.md)
- [docs/source-extraction-preview-v1.md](docs/source-extraction-preview-v1.md)
- [docs/cloud-open-callback-boundary-v1.md](docs/cloud-open-callback-boundary-v1.md)
- [docs/cloud-bulk-article-run-v1.md](docs/cloud-bulk-article-run-v1.md)
- [docs/nightly-site-inspection-morning-brief-v1.md](docs/nightly-site-inspection-morning-brief-v1.md)
- [docs/cloud-agent-positioning-v1.md](docs/cloud-agent-positioning-v1.md)
- [docs/cloud-agent-feedback-contract-v1.md](docs/cloud-agent-feedback-contract-v1.md)
- [docs/internal-ai-advisor-v1.md](docs/internal-ai-advisor-v1.md)
- [docs/site-ops-cloud-analysis-runtime-v1.md](docs/site-ops-cloud-analysis-runtime-v1.md)
- [docs/writing-assistance-evidence-history-2026-06.md](docs/writing-assistance-evidence-history-2026-06.md)
- [docs/cloud-production-deployment-history-2026-06-24.md](docs/cloud-production-deployment-history-2026-06-24.md)
- [docs/alipay-payment-and-portal-entry-hardening-2026-07-11.md](docs/alipay-payment-and-portal-entry-hardening-2026-07-11.md)
- [docs/ai-provider-env-config-retirement-2026-06-26.md](docs/ai-provider-env-config-retirement-2026-06-26.md)
- [docs/text-model-provider-integration-decision-2026-07-11.md](docs/text-model-provider-integration-decision-2026-07-11.md)
- [docs/cloud-runtime-reference-notes-2026-07.md](docs/cloud-runtime-reference-notes-2026-07.md)
- [docs/wordpress-ai-editor-runtime-closeout-2026-07-07.md](docs/wordpress-ai-editor-runtime-closeout-2026-07-07.md)
- [docs/wordpress-ai-generation-reference-stage-closeout-2026-07-12.md](docs/wordpress-ai-generation-reference-stage-closeout-2026-07-12.md)

## Test Entry For Agents

Cloud Python test dependencies live in this repository's `pyproject.toml`,
including the `dev` extra that provides `pytest`. From the repository root, use
the repo-local `.venv` created by `make bootstrap-dev`:

```bash
.venv/bin/python -m pytest tests/api/test_portal_routes.py
```

If `pytest` is missing, install the Cloud dev extra through the same project
root:

```bash
make bootstrap-dev
```

Do not use the old monorepo `uv --directory cloud ...` form in this standalone
repository; it points at a path that no longer exists here.

## Seed & Smoke Quick Entry

- local runtime seed: `pnpm run seed:smoke`
- local login seed: `pnpm run login:seed:dev`
- local portal real-site bootstrap: `pnpm run portal:bind:dev -- --site-id <site-id> --member-email <email>`
- scaffold one new Cloud route pack: `pnpm run scaffold:route -- --route-id <route-id>`
- scaffold one new Portal route pack: `pnpm run scaffold:portal-route -- --route-id <route-id>`
- local frontend dependency lock check: `pnpm run check:frontend-locks`
- local frontend health check: `bash scripts/dev-frontend-doctor.sh`
- local frontend dependency recovery: `bash scripts/dev-frontend-recover.sh`
- perimeter seam: `pnpm run check:perimeter`
- hosted runtime smoke: `pnpm run smoke:local-alpha`
- internal alpha onboarding smoke: `pnpm run smoke:internal-alpha-onboarding`
- deploy bundle smoke: `pnpm run check:e2e:deploy-bundle:smoke`
- remote WordPress cron helper: `pnpm run wp-cron:ssh -- <install|status|remove> [--site-url <wp-base-url>]`

## Scope

Phase 1 only covers:

- hosted model catalog
- hosted instance registry and capability tags
- hosted routing and execution
- hosted stats and health
- admin-only commercial core for accounts, sites, keys, plans, subscriptions,
  entitlement snapshots, usage meter ledger, and billing snapshots

This project does not define a second `abilities/workflows/projections` source of
truth. WordPress remains the control plane.

Local Python packaging artifacts such as `build/lib/**` and
`npcink_ai_cloud.egg-info/**` are not source truth. They are local setuptools
build outputs and should not be committed as routine source changes.

Current Cloud frontend status is bounded:

- `/(marketing)/*`
  - public product and onboarding surface
- `/admin/*`
  - operator / platform-admin / internal admin surface
- `/portal/*`
  - bounded authenticated member workspace
  - not a second control plane

These surfaces may expose account, billing, usage, connected sites, service
health, and cloud service entitlements, but they must not duplicate plugin
admin surfaces such as abilities, workflows, MCP, OpenClaw, or other
feature-control pages.

Broad model-intelligence, recognition-review, and platform model-operations
consoles have been removed. Bounded provider-connection operations and hosted
runtime-profile configuration remain available to platform admins as Cloud
runtime configuration. `catalog/platform-models` is retained only as runtime
metadata, not as a platform model-operations console.

## Identity Contract

Cloud product identity is frozen to two external identity types only:

- `platform_admin`
- `user`

These are the only product-layer identity semantics allowed in Cloud docs, API
contracts, and UI copy.

Boundaries:

- `platform_admin` owns the bounded Cloud operator surface
- `user` owns the bounded customer/account/site management surface
- database role values are also collapsed to these same two canonical values
- external payloads must treat `identity_type` as the primary identity field

Permission differences may continue to exist, but they must be expressed as
bounded actions or capability flags rather than new product identity labels.

Internal identity is frozen separately from those product labels:

- `principals.principal_id` is the single stable Cloud user identity. It is
  generated by the server as `prn_<uuid4 hex>` and is not changed when a user
  changes email, binds or unbinds a provider, joins another account, changes
  sites, or changes package.
- email and provider subjects are login aliases, not permanent identity keys.
  Email remains mutable on `principals`; QQ/OpenID/UnionID-style subjects belong
  only in `identity_provider_bindings`, where they map back to one
  `principal_id`.
- `account_id` identifies a commercial account/tenant, while `membership_id`
  identifies the relationship between a principal and an account. Neither is a
  user identity.
- sites are a separate resource dimension. A WordPress `wp_user_id`, when
  present as site-scoped integration metadata, is only an external reference;
  Cloud does not own the WordPress user directory or local permission truth.

## Current Status

Current repository status is:

- runtime foundation is landed for hosted runtime, routing, stats, usage, key
  auth, queued offload, and internal service provisioning
- admin-only commercial core is also landed for accounts, memberships, plans,
  subscriptions, entitlement snapshots, usage meter ledger, and billing
  snapshots
- operator-only commercial guidance is also landed for:
  - tiered `/admin/plans`
  - operator-managed subscription top-up
- bounded frontend surfaces do exist, but they are limited to:
  - service status root page
  - operator/platform-admin `/admin/*`
  - authenticated member `/portal/*`
- callback delivery worker, queue-backed public run cancel, runtime/operator
  diagnostics, operator-friendly service audit/commercial decision summary,
  multi-scope short-window rate limiting, internal service audit, runtime
  commercial decision trace, callback dispatch stale-lease reclaim, and
  retention cleanup service path are now landed as operational closure work
- cloud is also the canonical read owner for heavy `logs analytics`
  (`/v1/logs/analytics/summary`, `/tool-latency`, `/mcp-zone`,
  `/recommendations`); local/plugin paths may only assemble responses or
  degrade to cached snapshot / empty shape and must not reintroduce local heavy
  rebuilds
- durable `runtime_guard_events`, minimal app-side long-window cooldown, and
  deeper runtime/operator diagnostics are now landed as ops hardening work
- minimal commercial policy is now landed for subscription grace, budget
  soft-limit, runtime downgrade overrides, commercial policy inspect, and
  ledger-vs-snapshot reconciliation inspect
- bounded platform-admin seam is now landed for:
  - bounded `/admin` session cookie login via the one-time-generated admin key
  - accounts, sites, plans, subscriptions, runtime diagnostics, audit, and commercial decisions
- bounded portal auth seam is now landed for:
  - invited `user` email verification-code login
  - cookie-backed `/portal/*` member session
  - account/site-scoped portal workspace for site connection, usage, billing,
    Cloud audit, health, and diagnostics; signing keys are not a customer
    self-service surface

Still deferred in the current phase:

- stronger app-side abuse guard beyond the current minimal request/replay
  protections and cooldown windows
- richer long-window anomaly / burst heuristics and support-bundle/export grade
  operator explainability beyond the current bounded runtime pressure diagnostics
  and bounded abuse watchlists
- broader queued/running lease recovery beyond the current queue-backed runtime
  worker plus callback dispatch stale-lease reclaim
- customer-facing commercial front-office remains bounded:
  - seat lifecycle
  - real WeChat Pay checkout/payment provider integration
  - invoice/reconciliation
  - dunning-grade customer billing front-office
  - the current credit-pack catalog and payment-order state are launch
    service-plane details; Alipay page-pay can be enabled only with explicit
    RSA2 signing/verification configuration, while WeChat Pay remains deferred
    until provider signature verification, callback replay, and amount/currency
    matching are implemented
- richer platform admin directory/session inventory remains deferred

Commercial acceptance freeze:

- `plans + plan_versions` remain the only package execution truth
- `free / plus / pro / agency` remain tier templates
- `free / free_v1` is the explicit production free package
- `Free / Plus / Pro / Agency` remain the only current package presentation
  aliases
- points are presentation, not a ledger
- operator top-up means current billing period budget headroom only
- customer credit-pack purchases create payment-order-backed credit grants with
  a default 365-day validity window
- no wallet, no permanent credit, and no entitlement change without the Cloud
  payment-order or operator service-plane path in the current phase

## Validation Ladder

Cloud development and verification now follow a fixed three-layer order:

1. Local source workspace:
   - edit `app/**`, `frontend/**`, `tests/**`, contracts, and feature docs here first
   - this remains the only day-to-day development truth
2. Development Docker runtime:
   - run `docker-compose.dev.yml` either locally or through the approved
     [M4 Preview workflow](docs/m4-preview-development-v1.md)
   - when using M4 Preview, the authoring machine packages the current
     worktree while M4 alone builds and runs Docker; M4 has no Git role
   - validate the current branch with focused `pytest` and the narrowest
     applicable perimeter gate
3. Remote host deploy verification:
   - use `deploy-to-ssh-host.sh` only after local checks pass
   - remote hosts exist to prove `scp -> load/up -> migrate -> seed -> smoke`,
     real provider readiness, and real persisted-state compatibility
   - they do not replace the local development loop or become a second source
     of truth

Remote hosts are never the primary authoring environment. M4 Preview is an
explicit development-runtime exception, while release hosts remain
release-verification surfaces. If a problem appears only on a remote runtime,
treat it as deploy/config/state drift to be fixed back in the repo; do not edit
or commit source on that host.

Direct M4 syncs and deploys are candidate previews. After the reviewed pull
request is merged, use a clean, current `master` worktree to record the accepted
state without rebuilding by default:

```bash
pnpm run m4:preview:promote -- --pr <merged-pr-number>
```

See the [M4 Preview development workflow](docs/m4-preview-development-v1.md)
for the candidate/accepted contract and the explicit `--deploy` fallback.

## Borrowed Foundations

Cloud should keep borrowing mature infrastructure patterns instead of growing
bespoke second-truth systems:

- tracing and trace export stay on OpenTelemetry:
  - FastAPI request spans, `traceparent`, OTLP export, and the trace-sink seam
    already use OTel
  - prefer extending this path rather than inventing a custom trace protocol or
    local-only telemetry format
- commercial semantics may borrow OpenMeter-style language for:
  - entitlements
  - current-period grants/top-ups
  - reset windows
  - stale/fresh billing projections
  but the canonical truth in this repo stays `plans + plan_versions`,
  `account_entitlement_snapshots`, `usage_meter_events`, and `billing_snapshots`
  rather than a wallet, prepaid credit ledger, or second billing engine

## Focused Commands

Use the smallest Cloud lane that still covers the touched seam:

```bash
# all Cloud tests
pnpm run test

# focused local suites
pnpm run test:contract
pnpm run test:domain
pnpm run test:api

# recommended narrow lanes
pnpm run check:fast
pnpm run check:seam
pnpm run check:perimeter
```

- `test:contract`
  - contract truth for response shape and seam drift in `tests/contract/**`
- `test:domain`
  - domain/service behavior in `tests/domain/**`
- `test:api`
  - route/auth/api behavior in `tests/api/**`
- `check:fast`
  - default small Cloud lane: `contract + domain`
- `check:seam`
  - API seam lane: `api + perimeter`
- `check:perimeter`
  - deploy/auth/health/perimeter guard; do not replace it with `pytest` alone when auth or hosted seam changes

## Local Pytest Bootstrap

When running Cloud tests outside Docker, use the repo-local Python `3.12` venv
instead of assuming global `pytest` is present. After the root-level Cloud
migration, any old `cloud/.venv` created against `magick-ai/cloud` should be
treated as stale and rebuilt.

```bash
make bootstrap-dev
.venv/bin/pytest --version
```

`make bootstrap-dev` also installs the pinned `frontend` Node dependencies
needed by `pnpm run frontend:type-check` inside the hardening baseline.

Typical local runs:

```bash
make test-local PYTEST_ARGS='tests/api/test_web_routes.py -q'
make test-local
```

If `.venv/bin/pytest` points at a moved or missing worktree, delete `.venv`
and rerun `make bootstrap-dev`.

## Runtime Output vs Fixtures

`.runtime/**` is runtime-generated state for local jobs, deploy helpers,
and container execution. It is not a git-tracked source of truth.

- Runtime outputs stay under `.runtime/**`.
- Test fixtures belong under `tests/fixtures/runtime/**`.
If you need sample payloads for a test, add them under
`tests/fixtures/runtime/**` and load them explicitly from the test. Do not
commit new files under `.runtime/**`.

Current repo baseline:

- `git ls-files | rg '(^|/)\.runtime/'` should return no tracked runtime outputs.
- `git check-ignore -v --no-index .runtime/LATEST.txt` should resolve to the
  root [`.gitignore`](.gitignore) rule.

## Stability Baseline

Before the next Cloud feature round, rerun the fixed hardening baseline:

```bash
make baseline
```

`make baseline` runs the current repeatable checks:

- local `.venv` health via `.venv/bin/pytest --version`
- Agent/Workflow metadata anti-drift unit checks
- focused runtime and usage pytest lanes
- bounded key-list API pytest lane
- strict container `ruff` and `mypy`
- local wrapper checks:
  - `check:perimeter`
  - `frontend:type-check`
  - `frontend:lint`

For new Cloud Python work, add the changed-files static gate on top of the
baseline:

```bash
make lint-changed
```

`make lint-changed` auto-detects changed `app/**/*.py` and test Python files against the
merge-base with `origin/master` (falling back to `master` when needed), includes
staged / unstaged / untracked local edits, runs `ruff` correctness/import checks
(`I`, `F`, `E9`) on all changed Python files, and runs `mypy --follow-imports=skip`
on changed `app/**/*.py` files only. Use `CHANGED_BASE_REF=<ref>` when the
feature branch should compare against a different base.

After hardening-sensitive changes, also rerun the production packaging lane:

```bash
NPCINK_CLOUD_BASE_URL='https://cloud.example.com' \
NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST='https://cloud.example.com' \
NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST='cloud.example.com' \
docker compose -f docker-compose.prod.yml config >/dev/null
docker build -t npcink-cloud-prod-check -f Dockerfile .
```

For Python dependency changes, also run the blocking locked default and Zilliz
audit:

```bash
pnpm run check:python-dependency-audit
```

## Approved Feature Base

The next Cloud feature branch should start from the verified standalone Cloud
`master` branch:

- approved base branch: `master`
- required baseline before branching: `make baseline`
- remote state to confirm before branching: `git ls-remote --heads origin master`

Do not start the next Cloud feature from an older hardening worktree or archived
branch. Reconfirm `master` is synced with `origin/master` and rerun the baseline
before branching.

This rule exists to keep the current Cloud boundary intact:

- `magick-ai` remains the only local control-plane truth
- Cloud remains runtime/service-plane only
- Cloud feature work must not reintroduce a second control plane or a second
  source of truth

If a new Cloud feature is needed, create `codex/cloud-feature-<topic>` from the
synced standalone Cloud `master` branch after the baseline passes.

## Lint Debt Boundary

Cloud Python static-analysis debt is now part of the blocking baseline.

- Treat new `ruff check .` failures as regressions.
- Treat new `mypy app` failures as regressions.
- Do not mix unrelated lint-only rewrites into feature commits unless the
  changed feature needs that cleanup to keep the baseline green.
- For new Cloud Python changes, run `make lint-changed` as the minimum
  changed-files gate when the full `make baseline` lane would be too slow.
- The repo keeps a small explicit `ruff` per-file ignore list in
  [`pyproject.toml`](pyproject.toml); additions to that list should be treated
  as reviewed exceptions, not as the default way to land new code.

## Quick Start

```bash
cp .env.example .env
pnpm run dev
```

`pnpm run dev` starts the local core stack only: `postgres`, `redis`, `api`,
`frontend`, and `proxy`.

The development Compose wrapper loads `.env` and then `.env.local` for variable
interpolation, so local values win. Backend services still receive their
declared env files. The frontend receives only its explicit allowlist, including
the internal token required by the server-side Admin BFF; Admin, Portal,
database, provider, service-setting, and runtime-data encryption secrets are
not injected into it.

Use the worker profiles only when the current task needs them:

```bash
pnpm run dev:runtime   # adds the queued runtime worker
pnpm run dev:callback  # adds runtime and callback workers
pnpm run dev:ops       # adds runtime, callback, and ops cadence workers
```

### Docker Restart Recovery

Both `docker-compose.dev.yml` and `docker-compose.prod.yml` set
`restart: unless-stopped` on long-running services. This lets Docker restore the
Cloud stack after Docker Desktop or the Docker daemon starts again, as long as
the containers were not intentionally stopped with `docker compose stop` or
removed with `docker compose down`.

The dev and production restart policy covers `postgres`, `redis`, `api`,
`frontend`, `proxy`, `worker`, `callback-worker`, and `ops-worker`. The
production bundle does not start a second TLS edge, trace collector, or trace
store.

After changing restart policy or after finding stale exited containers, recreate
the stack once so existing containers pick up the compose policy:

```bash
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml up -d worker callback-worker ops-worker
```

Verify the local stack with:

```bash
docker compose -f docker-compose.dev.yml ps
docker inspect npcink-ai-cloud-api-1 --format '{{.HostConfig.RestartPolicy.Name}}'
curl -fsS http://127.0.0.1:8010/health/live
curl -fsS http://127.0.0.1:8010/ -o /dev/null -w '%{http_code}\n'
```

Expected results: the required containers are `Up`, the restart policy prints
`unless-stopped`, `/health/live` returns JSON with `status: ok`, and the frontend
entrypoint returns HTTP `200`. A running `proxy` with `502 Bad Gateway` usually
means `api` or `frontend` is not running yet.

### API reload recovery

The dev API runs `uvicorn --reload` so API-side Python edits are picked up
without a manual rebuild. The reload watcher is intentionally limited to `app`
and `migrations`, excludes `app/workers/*`, and sets
`--timeout-graceful-shutdown 5` so a stale in-process background task cannot
hold reload forever.

If an admin page such as `/admin/runtime-profiles` keeps showing a loading state
but has no visible error, first separate auth and API latency:

```bash
curl -i http://127.0.0.1:8010/admin/runtime-profiles
docker compose -f docker-compose.dev.yml logs --tail=120 api
docker compose -f docker-compose.dev.yml logs --tail=120 frontend
```

Normal unauthenticated behavior is a `307` redirect to
`/admin/login?redirect=...`. A stuck dev reload typically shows
`Waiting for background tasks to complete` in the API logs, while the frontend
logs show `/api/admin/*` requests taking tens of seconds. Recover with:

```bash
docker compose -f docker-compose.dev.yml restart api
```

After restart, the same admin data endpoints should return in milliseconds. Do
not treat this as a Cloud runtime routing bug unless the API has restarted and
the specific endpoint still returns an application error.

Worker-only edits should not reload the API. If `frontend` logs show
`/api/admin/runtime-profiles` taking tens of seconds after a worker file edit,
confirm the compose command still contains `--reload-exclude app/workers/*`
and recreate the dev API container:

```bash
docker compose -f docker-compose.dev.yml up -d api
```

If a queued runtime action such as audio preview reports
`runtime.provider_not_configured` even though the provider page is enabled and
healthy, check the runtime worker as well:

```bash
docker compose -f docker-compose.dev.yml logs --tail=120 worker
docker compose -f docker-compose.dev.yml restart worker
```

The dev worker refreshes DB-managed execution providers before each queue poll,
so provider connection edits should not require a worker restart after this
code is loaded. A restart is still useful when the worker process itself was
started before local code changes were mounted.

The default dev compose stack does not start `otel-collector`. To keep API
reloads responsive, it clears `NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT` for
local containers even if `.env` contains the production-style collector URL.
Opt in to local trace export only when a collector is actually running:

```bash
NPCINK_CLOUD_DEV_OTEL_EXPORTER_OTLP_ENDPOINT=http://host.docker.internal:4318/v1/traces pnpm run dev
```

Keep local-only debug credentials such as `NPCINK_CLOUD_INTERNAL_AUTH_TOKEN`,
`NPCINK_CLOUD_DEV_ADMIN_KEY`, `NPCINK_CLOUD_ADMIN_SESSION_SECRET`, and
`NPCINK_CLOUD_PORTAL_JWT_SECRET` in `.env.local` for dev Docker runs.
`.env.local` is gitignored, while production-style deploy helpers read
`.env.deploy` instead.

Runtime catalog metadata can also include Ollama-sourced model records in two modes:

- self-hosted/local node allowlist:
  - `NPCINK_CLOUD_OLLAMA_BASE_URL=http://host.docker.internal:11434`
  - `NPCINK_CLOUD_OLLAMA_MODEL_ALLOWLIST=llava:13b,bge-m3:latest`
- official Ollama cloud catalog:
  - `NPCINK_CLOUD_OLLAMA_BASE_URL=https://ollama.com`
  - `NPCINK_CLOUD_OLLAMA_API_KEY=<optional api key>`
  - `NPCINK_CLOUD_OLLAMA_CATALOG_ENABLED=true`
  - `NPCINK_CLOUD_OLLAMA_CATALOG_LIMIT=250`

The allowlist mode is best for private nodes you actually run. Ollama metadata is consumed as runtime catalog input only; it does not create a platform model operations surface.

For production-style remote deploys, start from [.env.example](.env.example),
then copy only non-secret bootstrap and runtime tuning values to `.env.deploy`.
The public origin and trusted host must be configured before the browser opens
`/setup`. Database credentials, the internal token, `NPCINK_CLOUD_ADMIN_KEY`,
`NPCINK_CLOUD_ADMIN_SESSION_SECRET`, service/runtime encryption roots, and the
Portal JWT root are generated or persisted under protected `shared/config/`;
they must not be added to `.env.deploy`.

On the first deploy, the host helper initializes setup authentication without
putting a usable code in CI output. Issue the usable `nca_setup_...` replacement
from the active release in an interactive SSH TTY, then open `/setup`, enter the
Cloud origin and Alibaba RDS PostgreSQL 18 details, verify the private TLS
connection, and save the one-time `nca_admin_...` key.
The canonical operator procedure is
[Cloud First Install with Alibaba RDS PostgreSQL 18](docs/cloud-first-install-rds-pg18-runbook.md),
and the frozen API/security contract is
[Cloud First Install Contract v1](docs/cloud-first-install-contract-v1.md).

After the first platform-admin login, configure Portal public URL, QQ login,
and Portal email delivery in `/admin/service-settings`. These service settings
are stored by Cloud runtime storage and are no longer read from `.env`.
Secret values saved through `/admin/service-settings` use the active `sse.v1`
key family. A fresh PostgreSQL 18 installation does not import legacy raw rows
or consume the retired P1-E06 migration evidence; historical databases are not
accepted through a compatibility chain.

The runtime-data secret and key ID are not ordinary configuration-only rotation
values. Changing them requires the stopped-writer inventory, backup,
re-encryption, verification, and matched rollback procedure in
[`deploy/OPS_PLAYBOOK.md`](deploy/OPS_PLAYBOOK.md). Normal runtime has no old-key
or raw-ciphertext fallback.

If a development deploy still has Portal public URL, QQ login, or SMTP values
in `.env`, import the current `NPCINK_CLOUD_*` values once before removing
those service-setting keys:

```bash
docker compose -f docker-compose.dev.yml run --rm api \
  python -m app.dev.import_service_settings_from_env
```

The import command writes only to `service_settings`, keeps secret values out of
stdout, and does not re-enable `.env` fallback.

Additional hardening rules now enforced:

- production API runs behind `gunicorn` + `uvicorn.workers.UvicornWorker`
- admin-key login is a separate secret from internal service auth outside development/test
- browser same-origin checks use explicit origin allowlists and fail closed on bad forwarded origin input
- trusted host / forwarded host validation no longer assumes ingress is always configured correctly
- callback registration and dispatch only accept `https://` targets that resolve to public IP space
- `NPCINK_CLOUD_DEBUG_LOCAL_ORIGIN_ALLOWLIST` defaults to empty and only applies in `development` / `test`

## Release Smoke

Before a formal deploy, run the combined release smoke:

Create a mode-`0600` JSON credentials file outside the repository with the
required `NPCINK_CLOUD_INTERNAL_AUTH_TOKEN`, `NPCINK_CLOUD_ADMIN_KEY`, Portal,
and signed-runtime smoke fields listed in
[deploy/release-smoke.env.example](deploy/release-smoke.env.example), then run:

```bash
bash deploy/release-smoke.sh \
  --base-url https://cloud.example.com \
  --credentials-file /secure/path/release-smoke-credentials.json
```

The release smoke verifies:

- `GET /health/live`
- `GET /health/ready` with `X-Npcink-Internal-Token`
- `GET /`
- `GET /portal/login`
- `POST /portal/v1/auth/code/request`
- `POST /portal/v1/auth/code/verify`
- `GET /portal/v1/session`
- `GET /admin/login`
- `POST /admin/auth/login`
- `GET /admin/session`

This workspace now also keeps a local remote-target handoff at
[deploy/WORKSPACE_TARGET.md](deploy/WORKSPACE_TARGET.md) and a sourceable shell
target file at [deploy/workspace-target.env.sh](deploy/workspace-target.env.sh).

## External WordPress Cron

Use the deploy helper when a remote host should own the external scheduler for a
WordPress site whose `wp-config.php` keeps `DISABLE_WP_CRON=true`.

Current posture:

- customer-facing default remains standard `WP-Cron`
- production recommendation is server cron calling `wp-cron.php`
- this helper is only for deployments that intentionally disable automatic `WP-Cron`
- it does not replace local schedule ownership or create a second scheduler truth

Typical flow:

```bash
source deploy/workspace-target.env.sh
pnpm run wp-cron:ssh -- install --site-url https://example-wordpress-site.test
pnpm run wp-cron:ssh -- status
```

Default behavior:

- installs one managed `crontab` block on the remote host
- uses `flock` to avoid overlapping runs
- calls `<site>/wp-cron.php?doing_wp_cron=cloud`
- defaults to `*/5 * * * *`, configurable via `NPCINK_CLOUD_WP_CRON_SCHEDULE`

Remove it with:

```bash
source deploy/workspace-target.env.sh
pnpm run wp-cron:ssh -- remove
```

Platform identity/admin and portal references:

- current bounded admin cleanup closeout:
  [admin-surface-cleanup-closeout-2026-07-02.md](docs/admin-surface-cleanup-closeout-2026-07-02.md)
- current account/portal stage closeout:
  [cloud-account-portal-stage-closeout-summary-2026-06-29.md](docs/cloud-account-portal-stage-closeout-summary-2026-06-29.md)
- current portal user management history:
  [admin-portal-user-management-history-2026-06-29.md](docs/admin-portal-user-management-history-2026-06-29.md)
- current payment seam summary:
  [commercial-billing-payment-stage-summary-2026-06-23.md](docs/commercial-billing-payment-stage-summary-2026-06-23.md)
- payment gateway contract:
  [payment-gateway-contract-v1.md](docs/payment-gateway-contract-v1.md)

Health endpoints:

- `GET /health/live`
- `GET /health/ready` with `X-Npcink-Internal-Token`

If you need `/internal/*` routes in dev or prod, set
`NPCINK_CLOUD_INTERNAL_AUTH_TOKEN`. Internal routes fail closed when the token is
not configured.

Internal read-only detail examples:

- `GET /internal/service/admin/image-source-metrics` summarizes image-source
  runs, fast-first usage, deferred enrichment, provider errors, and latency
  without returning queries, prompts, result payloads, provider secrets, or any
  WordPress write authority.

Portal member auth:

- portal members are invite-only `user` identities
- browser login is two-step:
  - `POST /portal/v1/auth/code/request`
  - `POST /portal/v1/auth/code/verify`
- successful verification establishes the cookie-backed portal session used by
  `/portal/*` and `/portal/v1/*`
- WordPress addon authorization uses the bounded Portal connection seam:
  - `POST /portal/v1/addon-connections` requires a Portal session and issues a
    short-lived return code after creating or activating the site connection
  - `POST /portal/v1/addon-connections/exchange` consumes that one-time code
    from the WordPress server and returns the customer-facing Cloud API key
- production deploys should set:
  - `NPCINK_CLOUD_PORTAL_JWT_SECRET`
- production deploys should configure in `/admin/service-settings`:
  - Portal public URL
  - QQ login, when enabled
  - SMTP sender settings for verification-code delivery
Platform admin key auth:

- Cloud now assumes one non-self-serve `platform_admin`
- current bounded login path:
  - `POST /admin/auth/login`
  - request body: `{"admin_key":"<current admin key>"}`
  - response establishes `npcink_admin_session_token`
- current admin session inspect path:
  - `GET /admin/session`
- current visible admin pages:
  - `GET /admin`
  - `GET /admin/plans`
  - `GET /admin/accounts/{account_id}`
  - `GET /admin/sites/{site_id}`
- current `/admin` overview now also includes:
  - one `Identity Layers` block for platform roles vs customer portal roles
  - one `Plan catalog` block derived from live `plan_distribution`
  - quick drill-in links to `/admin/plans`, `/admin/accounts`, and `/admin/subscriptions`
- platform-admin login uses the configured single platform admin reference
  and does not require a separate identity-provisioning surface
- current operator runbook for lean validation:
  - [deploy/OPS_PLAYBOOK.md](deploy/OPS_PLAYBOOK.md)
Buyer-facing web routes:

- `GET /`
- `GET /portal/login`
- `GET /portal`
- `GET /portal/usage`
- `GET /portal/billing`
- `GET /portal/audit`
- `GET /portal/logout`

These routes are a bounded Cloud service status and portal layer, not a
customer-facing commercial front-office. Marketing pages, standalone top-up
catalog request pages, impersonation pages, compliance pages, and request queues
are intentionally removed. The Portal usage surface may show credit-pack
catalog, payment orders, and simulated payment status as bounded billing detail;
real external payment provider checkout remains gated by
[payment-gateway-contract-v1.md](docs/payment-gateway-contract-v1.md).

## Verification Quickstart

For the fastest local verification loop:

1. Configure local portal auth in `.env`:
   - `NPCINK_CLOUD_PORTAL_JWT_SECRET=dev-portal-jwt-secret-with-at-least-thirty-two-bytes`
2. Start local Cloud:
   - `pnpm run dev`
   - optional frontend auto-sync loop: `pnpm run frontend:watch`
3. For stable local admin/portal debugging, seed the fixed local login data:
   - `pnpm run login:seed:dev`
   - default site: `site_smoke`
   - default portal email: `portal-demo@example.com`
4. Prefer binding Portal to one already provisioned real site:
   - `pnpm run portal:bind:dev -- --site-id <site-id> --member-email <email>`
5. If the environment is empty and you need a custom site, seed a runtime baseline and then bind Portal:
   - `pnpm run seed:smoke`
   - `pnpm run portal:bind:dev -- --site-id <site-id> --member-email <email>`

The real-site bootstrap path reuses:

- one already provisioned account + site + subscription
- current usage meter events and billing state for that site
- existing site keys; `--issue-key` is host-local only and requires
  `NPCINK_CLOUD_SECRET` from a protected process environment. The remote
  `portal:bind:ssh` wrapper intentionally rejects key issuance.

The runtime seed command creates a minimal site + subscription baseline for
operator smoke, and does not create portal members or portal-facing sample data.

Primary local verification routes:

- `http://127.0.0.1:8010/admin/login`
- `http://127.0.0.1:8010/portal/login`
- `http://127.0.0.1:8010/portal`
- `http://127.0.0.1:8010/portal/overview`

`portal:bind:dev` marks its output as `"data_mode": "real_site_bootstrap"`
and does not synthesize seeded runs or usage. It only binds a portal member
to an existing site and optionally rebuilds the current billing snapshot from
real ledger data.

For remote portal verification after deploy:

1. Load the saved target:
   - `source deploy/workspace-target.env.sh`
2. Prefer binding Portal to one already provisioned remote site:
   - `pnpm run portal:bind:ssh -- --site-id <site-id> --member-email <email>`
3. Run the remote portal smoke against the same site:
   - `pnpm run portal:smoke:ssh -- --site-id <site-id> --member-email <email>`
4. Or fold the same post-deploy verification into the deploy command:
   - `pnpm run deploy:ssh -- --with-portal-smoke --site-id <site-id> --member-email <email>`

`portal:bind:ssh` is the preferred remote path once a real site and
subscription already exist on the server. It binds one portal member to that
site and exposes the current real ledger/snapshot state instead of generating
seeded runs.

`deploy:ssh -- --with-portal-smoke` requires a real site and member email.
It runs real-site bootstrap plus portal smoke for the given `--site-id`.

Release verification should use the formal portal code path. Dev-only
development-code helpers live under `deploy/dev/`:

- `deploy/dev/remote-portal-login-code-smoke.sh`

For formal operator procedures, see [deploy/OPS_PLAYBOOK.md](deploy/OPS_PLAYBOOK.md).
For the current portal/account state, see
[cloud-account-portal-stage-closeout-summary-2026-06-29.md](docs/cloud-account-portal-stage-closeout-summary-2026-06-29.md).

## Admin Console

Cloud now also exposes one internal-only admin console:

- `GET /admin`
- `GET /admin/accounts`
- `GET /admin/accounts/{account_id}`
- `GET /admin/sites`
- `GET /admin/sites/{site_id}`
- `GET /admin/subscriptions`
- `GET /admin/subscriptions/{subscription_id}`
- `GET /admin/plans`
- `GET /admin/login`
- `POST /admin/auth/login`
- `GET /admin/session`
- `GET /admin/logout`

Admin auth is bounded to the dedicated one-time-generated admin-key seam:

- `POST /admin/auth/login` with the saved one-time `nca_admin_...` key
  establishes one bounded ops cookie session
- production stores only the key digest in protected runtime configuration;
  the plaintext is not an environment variable
- it does not replace future formal admin auth or IAM

Current `/admin` overview is not just counters. It now also includes:

- expiring subscriptions drill-down links for 7/30 day windows
- a `Past due or suspended subscriptions` table
- a `Subscriptions expiring within 30 days` table
- direct runtime diagnostics links for queued runs, callback failures, and
  guard events

For backend-only/admin-only remote updates, you can now skip rebuilding the
frontend image:

- `pnpm run deploy:ssh -- --skip-seed --skip-smoke --skip-frontend-image`

This keeps the existing remote frontend container and only refreshes the
backend/admin surface, which is useful when Docker Hub or frontend build churn
would otherwise block one small ops change.

## Internal Admin Surface

The bounded internal admin surface is now landed. It is:

- internal-only
- service-plane writable for commercial operations
- service-plane bounded
- centered on overview + accounts + sites + subscriptions
- not a full IAM/admin suite

Plan and handoff truth:

- [admin-surface-cleanup-closeout-2026-07-02.md](docs/admin-surface-cleanup-closeout-2026-07-02.md)
- [admin-customer-surface-consolidation-history-2026-06-30.md](docs/admin-customer-surface-consolidation-history-2026-06-30.md)

Current internal admin routes:

- `GET /admin`
- `GET /admin/accounts`
- `GET /admin/accounts/{account_id}`
- `GET /admin/sites`
- `GET /admin/sites/{site_id}`
- `GET /admin/subscriptions`
- `GET /admin/subscriptions/{subscription_id}`
- `GET /admin/login`
- `POST /admin/auth/login`
- `GET /admin/session`
- `GET /admin/logout`

Current internal admin API facade:

- `GET /internal/service/admin/overview`
- `GET /internal/service/admin/accounts`
- `GET /internal/service/admin/accounts/{account_id}`
- `GET /internal/service/admin/sites`
- `GET /internal/service/admin/sites/{site_id}`
- `GET /internal/service/admin/subscriptions`
- `GET /internal/service/admin/subscriptions/{subscription_id}`

Current admin list filters:

- accounts: `status`, `member_ref`, `expires_before`
- sites: `status`, `account_id`, `subscription_status`, `expires_before`
- subscriptions: `status`, `account_id`, `site_id`, `plan_id`, `expires_before`

Current login shape:

- open `/admin/login`
- provide the saved current `nca_admin_...` key
- the page sets one bounded admin cookie session for `/admin`

This remains an internal runtime/operations surface. It is not a customer portal
and not a second control plane.

In production-style deploys, the bundled proxy forwards `/admin` and `/admin/*`
as the only public platform-admin surface. Legacy `/ops/*` paths are removed.

Current acceptance and cleanup receipts:

- [admin-surface-cleanup-closeout-2026-07-02.md](docs/admin-surface-cleanup-closeout-2026-07-02.md)
- [admin-runtime-surface-cleanup-closeout-2026-07-01.md](docs/admin-runtime-surface-cleanup-closeout-2026-07-01.md)

Current auth decision stays bounded:

- keep `platform_admin token login + user email verification code` as the
  current bounded seam
- remote smoke should use `/portal/v1/auth/code/request` and
  `/portal/v1/auth/code/verify`
- do not add email+password, public registration, or persistent session
  inventory in the current lane

Portal email login delivery:

- `POST /portal/v1/auth/code/request` issues a one-time verification code for a
  portal member email
- `POST /portal/v1/auth/code/verify` establishes the cookie-backed portal
  session from that code
- if SMTP is configured, Cloud sends the verification code by email and does
  not echo the raw code back to the browser
- when the request carries a supported UI locale, email subject/body follow that
  locale; current supported values are `en`, `zh-CN`, and `zh-TW`
- if SMTP is not configured, development/test mode falls back to returning the
  verification code in-app for local debugging
- configure Portal public URL and SMTP delivery in `/admin/service-settings`;
  SMTP password is write-only and runtime delivery has no `.env` fallback

For Alibaba Cloud enterprise mailbox, point the service settings at the SMTP
host/port and SSL or STARTTLS mode provided by your mailbox admin panel.
This keeps Cloud generic while still supporting Aliyun enterprise mail as the
actual sender.

Portal email self-test:

- `POST /internal/portal/email/test`
- requires `X-Npcink-Internal-Token` and `Idempotency-Key`
- request body:

```json
{"recipient_email":"you@example.com"}
```

- example:

```bash
curl -X POST http://127.0.0.1:8000/internal/portal/email/test \
  -H "Content-Type: application/json" \
  -H "X-Npcink-Internal-Token: ${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN}" \
  -H "Idempotency-Key: portal-email-test-001" \
  -d '{"recipient_email":"you@example.com"}'
```

Provider execution modes:

- default: sample mode, no external provider calls
- configure model provider channels in `/admin/ai-resources`;
  provider keys are stored as DB provider connections, not `.env.local` values
- the OpenAI provider ceiling defaults to 60 seconds so an explicitly bounded
  long-form runtime request can complete; each runtime request still supplies
  its own timeout and shorter tasks remain constrained by the smaller value

Provider integration boundary:

- upstream providers/gateways are provider sources, not Hosted Catalog truth
- `litellm / vllm / tei / openrouter` use namespaced `model_id` values inside
  `catalog_models` to avoid collisions with existing providers
- contract: `docs/contracts/cloud-provider-integration-matrix-v1.md`

Public runtime surface:

- `GET /v1/catalog/revision`
- `GET /v1/catalog/models`
- `GET /v1/catalog/models/{model_id}`
- `POST /v1/runtime/resolve`
- `POST /v1/runtime/execute`
- `GET /v1/runs/{run_id}`
- `POST /v1/runs/{run_id}/cancel`
- `GET /v1/runs/{run_id}/result`
- `GET /v1/stats/instances/{instance_id}`
- `GET /v1/stats/profiles/{profile_id}`
- `GET /v1/usage/summary`

Public runtime auth:

- site-scoped `HMAC-SHA256` headers
- public signed `POST` 额外要求 `X-Npcink-Nonce`
- `catalog:read` required for `/v1/catalog/*`
- runtime/runs/stats keep their existing scope checks

Public runtime commercial seam:

- `POST /v1/runtime/resolve` and `POST /v1/runtime/execute` now accept
  `ability_family`
- allowed values: `text`, `vision`, `workflow`, `automation`, `mcp`,
  `openclaw`
- Cloud uses `ability_family + channel + execution_kind + execution_tier +
  data_classification` for entitlement/metering only; plugin governance truth
  remains local
- current commercial gate can now apply minimal subscription grace and budget
  soft-limit allowance with runtime downgrade overrides; deny paths still
  continue to use `commercial.subscription_inactive`,
  `commercial.entitlement_denied`, `commercial.quota_exceeded`, and
  `commercial.concurrency_exceeded`

Site provisioning prerequisite:

- public runtime requests never auto-create `sites` or `site_api_keys`
- `/v1/runtime/*`, `/v1/runs/*`, and `/v1/stats/*` only accept a pre-provisioned
  `active` site
- in dev/test, provision a site via `python -m app.dev.seed_runtime ...`; in the
  product model, provisioning/activation/suspension belongs to Cloud service
  operations, not the runtime request path

Site API key lifecycle prerequisite:

- public runtime auth only accepts `active` keys
- any key with `revoked_at` set, or `expires_at <= now`, is rejected as
  `auth.invalid_key`
- `create / rotate / revoke / expire` remain Cloud service-plane or
  internal-ops actions; runtime request paths only consume issued key state
- service-plane key lifecycle audit now lands in `service_audit_events`, but it
  is still an internal/admin evidence surface rather than a customer-facing
  portal feature

Internal operations surface:

- `POST /internal/catalog/refresh`
- `POST /internal/health/providers/scan`
- `POST /internal/service/accounts`
- `POST /internal/service/accounts/{account_id}/memberships`
- `POST /internal/service/sites`
- `POST /internal/service/sites/{site_id}/activate`
- `POST /internal/service/sites/{site_id}/suspend`
- `GET /internal/service/sites/{site_id}/keys`
- `POST /internal/service/sites/{site_id}/keys`
- `POST /internal/service/sites/{site_id}/keys/{key_id}/rotate`
- `POST /internal/service/sites/{site_id}/keys/{key_id}/revoke`
- `POST /internal/service/sites/{site_id}/keys/{key_id}/expire`
- `POST /internal/service/plans`
- `POST /internal/service/plans/{plan_id}/versions`
- `POST /internal/service/sites/{site_id}/subscription`
- `POST /internal/service/sites/{site_id}/subscription/suspend`
- `POST /internal/service/sites/{site_id}/subscription/cancel`
- `GET /internal/service/sites/{site_id}/usage-meter`
- `GET /internal/service/sites/{site_id}/commercial-policy`
- `GET /internal/service/sites/{site_id}/billing-snapshots`
- `GET /internal/service/sites/{site_id}/billing-snapshots/reconciliation`
- `POST /internal/service/sites/{site_id}/billing-snapshots/rebuild`
- `GET /internal/service/audit-events`
- `GET /internal/service/audit-events/summary`
- `GET /internal/service/ops/cadence`

Bounded admin audit UX stays split on purpose:

- raw operator trail backlinks continue to point at `/api/admin/audit-events?...`
- operator-facing inline summary panels continue to read `/api/admin/audit-events/summary?...`
- do not add a standalone admin audit detail page unless the bounded seam changes by contract first
- `GET /internal/service/commercial-decisions`
- `GET /internal/service/commercial-decisions/summary`
- `GET /internal/service/runtime/diagnostics/summary`
- `GET /internal/service/runtime/diagnostics/runs`
- `GET /internal/service/runtime/diagnostics/abuse-guard`
- `GET /internal/service/runtime/diagnostics/guard-events`
- `POST /internal/service/runtime/retention/cleanup`

Internal auth:

- `X-Npcink-Internal-Token`
- `Idempotency-Key` on POST
- repeated internal POST replay markers are rejected as `auth.replay_blocked`
- not interchangeable with the public runtime HMAC headers
- also required for `GET /health/ready`

Catalog query extras:

- `GET /v1/catalog/models?recommended_for=text.balanced`
- response payloads include `recommended_sets` for the default hosted profiles

Deploy perimeter:

- production uses `trusted external Edge -> bundled NGINX -> Gunicorn`; the
  operator-owned Edge terminates public TLS and owns public `80/443`.
- the bundled NGINX publishes only the loopback deployment port. Neither the
  exact release bundle nor the raw `api` container publishes public `80/443`.
- Keep `/internal/*` behind allowlist or private ingress; the bundled proxy only
  forwards those paths for loopback/private callers and does not expose them as
  public routes.
- Keep `GET /health/ready` on the same internal/allowlisted path as
  `/internal/*`; only `GET /health/live` remains a minimal public liveness
  probe.
- Keep `/docs` and `/redoc` disabled in production.
- The bundled proxy owns the Cloud route, media-transfer, rate, connection,
  timeout, and sanitized-log policy. TLS termination, source restriction, IP
  allowlist, WAF, and stronger edge controls belong to the external Edge.
- The external Edge must replace incoming client-controlled forwarded headers.
  NGINX trusts real-client headers only from the pinned Compose gateway, and
  Gunicorn trusts forwarded headers only from the pinned NGINX address.
- `remote-smoke.sh` also verifies `/docs`, `/redoc`, and internal POST fail
  closed without `X-Npcink-Internal-Token`.

Queued whole-run offload behavior:

- public runtime intake still only accepts `inline` and `whole_run_offload`
- `step_offload` remains an internal local seam and is not a public Cloud ingress mode
- WordPress local schedule and batch-policy ownership stays local; Cloud queue workers only own hosted runtime execution/detail
- `execution_pattern=whole_run_offload` plus `task_backend.enabled=true` returns a
  hosted queued `run_id` plus an explicit `canonical_run_id` backlink
- `python -m app.workers.runtime_queue` is now the default worker command in both
  dev and prod compose files
- `python -m app.workers.callback_dispatch` now owns terminal callback delivery
  as a separate worker lane in production-style deploys
- `python -m app.workers.ops_cadence` is now the managed ops cadence lane for
  retention cleanup plus the current summary/rollup tasks
- worker heartbeats now land in `service_audit_events` as `worker.heartbeat`
  so `worker`, `callback-worker`, and `ops-worker` liveness can be checked
  without adding a second scheduler or registry
- each worker poll now drains up to `NPCINK_CLOUD_RUNTIME_WORKER_BATCH_SIZE`
  queued runs and up to `NPCINK_CLOUD_RUNTIME_CALLBACK_BATCH_SIZE` pending
  callbacks before sleeping again; this keeps queue orchestration in the worker
  without turning Redis into a second truth source
- Redis is only a wake-up signal for the worker; `run_records` remains the
  hosted status/result source, while local polling remains the canonical read
  surface
- callback delivery, worker cadence, and backlog diagnostics are runtime evidence lanes, not a second queue or scheduler truth
- `resolve / execute / runs / result` now also expose `run_lifecycle`, which
  normalizes `requested -> queued|processing -> terminal -> retention`
- `POST /v1/runs/{run_id}/cancel` is now available for queue-backed runs;
  queued runs can be canceled immediately, while `running` cancel remains
  best-effort and only takes effect at worker attempt boundaries, not as a
  provider-level hard abort
- `callback_url` now schedules worker-driven terminal callback delivery;
  `run_lifecycle.callback` exposes `pending_terminal / pending / dispatching /
  delivered / failed`; stale `dispatching` callbacks older than the current
  stale threshold are now reclaimed back to `pending` before redispatch, while
  polling remains the canonical read surface and broader run lease recovery
  still remains deferred
- execution queue claiming and callback dispatch now run in separate worker
  entrypoints so execution backlog and callback backlog can be operated
  independently without introducing a second queue truth
- callback dispatch polling is controlled by
  `NPCINK_CLOUD_RUNTIME_CALLBACK_WORKER_POLL_SECONDS`
- once `retention_expires_at` is in the past, `GET /v1/runs/{run_id}/result`
  returns `410 runtime.result_expired`; asynchronous cleanup may purge the
  stored inline result later without changing the terminal run record
- `service_audit_events` now records the managed cadence executions for
  retention cleanup, usage rollup, router diagnostics summary, latency probe
  summary, provider degradation summary, and provider health scan summary so
  operators can inspect freshness without inventing a second scheduler truth

Public runtime abuse boundary:

- app-side rejects malformed `Idempotency-Key` values and payloads above the
  current request-size cap before they reach runtime business logic
- public signed POST requests must also carry `X-Npcink-Nonce`; reused nonce
  values are rejected as `auth.replay_blocked`
- public short-window rate limiting now enforces `site + key + client IP`
  scopes before runtime business logic and still returns stable
  `429 auth.rate_limit_exceeded`
- public signed POST requests now also enforce a minimal long-window cooldown
  on `site + key + client IP` based on durable `runtime_guard_events`
- `/internal/*` POST replay markers are stored in the same short-TTL receipt
  store and are also rejected as `auth.replay_blocked` when reused
- internal short-window rate limiting now enforces both global internal-token
  and client-IP scopes before mutating service-plane requests are accepted
- internal POST requests now also enforce a minimal long-window cooldown on
  `internal token + client IP` based on durable `runtime_guard_events`
- `GET /internal/service/runtime/diagnostics/abuse-guard` summarizes recent
  replay/short-window receipts plus cooldown summaries for operator
  investigation; it now also classifies per-scope `request_burst` /
  `reject_storm` severity, attaches reason codes and guard-event-code
  breakdown, and emits a bounded watchlist for operator triage; it is not a
  customer-facing portal surface
- `GET /internal/service/runtime/diagnostics/summary` now also exposes bounded
  queue/cancel/callback pressure state, oldest-age seconds, thresholds, and
  reason codes so operators can distinguish a fresh backlog from a stale one;
  callback summary now also marks `recoverable_dispatching` plus the bounded
  reclaim action used for stale callback leases
- `GET /internal/service/runtime/diagnostics/backlog` now provides queued vs
  running backlog observability by `site_id`, `ability_family`, or
  `execution_pattern`, including oldest/p95 age, fresh-vs-aging-vs-stale
  buckets, bottleneck classification, and lease-recovery input counts; this is
  a preflight operator surface, not queued/running lease recovery itself
- `GET /internal/service/runtime/diagnostics/runs` now accepts
  `queued_stale`, `running_stale`, `cancel_stuck`, and `callback_overdue`
  drill-down filters in addition to the earlier coarse issue kinds
- stale callback dispatch lease recovery now also lands
  `runtime.callback_dispatch_recovered` events in `service_audit_events` for
  operator follow-up; it is not a customer-facing portal surface
- `GET /internal/service/runtime/diagnostics/guard-events` exposes recent
  durable request-guard evidence for operator drill-down; it is not a
  customer-facing portal surface
- request-guard reject evidence now lands in `runtime_guard_events`
- replay truth for `/v1/runtime/execute` remains `run_records(site_id,
  idempotency_key)`; this does not move to Redis
- commercial ledger truth remains `usage_meter_events`; `usage_rollups` are
  projections and `billing_snapshots` must remain rebuildable from the ledger
- commercial allow/deny decisions now land in `commercial_decision_events`,
  while internal mutating service ops land in `service_audit_events`
- app-side still does not own a full site/key/IP rate-limit or abuse-policy
  framework; the current in-app protections are intentionally minimal
- TLS termination, rate limit, IP allowlist, source restriction, WAF, and
  private ingress remain host/reverse-proxy responsibilities

## Local Commands

```bash
make dev
make test
make lint
make migrate
make seed-dev
make rollup
make bundle
make deploy-smoke
make deploy-ssh
make provider-status
```

`make deploy-smoke` currently reuses
`../npcink-abilities-toolkit/tests/e2e/cloud-deploy-bundle-smoke-flow.sh` as a plugin-side e2e
test asset. This is a temporary test dependency for deploy verification only;
it does not move control-plane ownership, settings truth, or runtime authorship
back into the plugin workspace.

Example dev seed (local development only; never reuse this sample secret in a
deployed environment):

```bash
docker compose -f docker-compose.dev.yml run --rm api alembic upgrade head
docker compose -f docker-compose.dev.yml run --rm api python -m app.dev.seed_runtime \
  --site-id site_smoke \
  --key-id key_default \
  --secret local-dev-only-change-me
```

If cross-arch Docker builds are unstable from your network, you can also export
optional pip mirror args before `make bundle` or `deploy-to-ssh-host.sh`:

```bash
export NPCINK_CLOUD_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export NPCINK_CLOUD_PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
```

`deploy/bundle-images.sh` passes these optional values to BuildKit as secret
mounts. Do not translate them into Docker `--build-arg` values; index URLs can
contain credentials and build arguments may be retained in image provenance.

With a real API key, `POST /internal/catalog/refresh` plus a valid
`X-Npcink-Internal-Token`, and
`python -m app.workers.catalog_refresh` fetch `/models` from the configured
provider instead of using the built-in sample catalog. Provider credentials and
provider-specific runtime configuration are managed as DB provider connections
through `/admin/ai-resources`; unconfigured sample adapters do not silently alter
default routing.

For router-performance offload staging, `python -m app.workers.router_performance_snapshot`
now acts as a one-shot cadence worker. It enumerates active sites, builds the
last complete-hour `cloud_router_performance_snapshot` batches with the same
runtime-derived `preset_id` / `guard_fail` / proxy `quality/reward` shape used
by the stats route, persists one replay-safe delivery buffer row per site/window,
and logs a per-site batch summary. If site metadata explicitly provides
`router_performance_callback_url`, `router_performance_callback_key_id`, and
`router_performance_callback_secret` (or the nested
`projection_callbacks.router_performance_snapshot.*` equivalents), the worker can
also POST the exact-window batch to the WordPress callback route
`/wp-json/npcink/open/v1/router/performance-snapshot/callback`. This remains
optional and metadata-gated; WordPress fetch/apply still owns cursor advance and
final snapshot truth.

For router-diagnostics offload staging, `python -m app.workers.router_diagnostics_summary`
now acts as a parallel one-shot cadence worker. It enumerates active sites,
builds runtime-derived `cloud_router_diagnostics` summaries for the current
recent-minute window, and logs per-site regression/quality counters plus item
counts. It does not invent WordPress control-plane truth such as real
`config_revision`, `enabled_total`, or `high_risk_count`; those remain
WordPress-owned and the worker keeps them neutral while the WordPress fetch/apply
lane remains the delivery owner. If site metadata explicitly provides
`router_diagnostics_callback_url`, `router_diagnostics_callback_key_id`, and
`router_diagnostics_callback_secret` (or the nested
`projection_callbacks.router_diagnostics.*` equivalents, or a derivable
`public_base_url` plus key/secret), the worker can also POST the exact batch to
`/wp-json/npcink/open/v1/router/diagnostics/callback`; otherwise it keeps
relying on the delivery buffer plus pull fallback.

For latency-probe offload staging, `python -m app.workers.latency_probe_summary`
now acts as a one-shot cadence worker. It enumerates active sites, selects
recently active hosted instances from provider-call activity, and logs
instance-level summaries using the same `GET /v1/stats/instances/{instance_id}`
semantics already consumed by the WordPress hosted-only fetch/apply lane. It
does not write WordPress `routing.latency_tier`, `health` meta, or local-instance
probe truth; those remain WordPress-owned.

For alert-evaluate offload staging, `python -m app.workers.alert_provider_degradation`
now acts as a one-shot cadence worker for the first cloud-native rule type. It
enumerates active sites, reuses the existing `GET /v1/alerts/provider-degradation`
projection semantics, and logs per-site event batches for `provider_degradation`
only. WordPress still owns incident apply, delivery, and all non-provider rule types.

For managed minimum operations, `python -m app.workers.ops_cadence` now owns the
official cadence lane for:

- runtime retention cleanup
- usage rollup generation
- router diagnostics summary
- latency probe summary
- alert provider degradation summary
- provider health scan

Cadence polling and per-task intervals are configured with:

```bash
NPCINK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS=60
NPCINK_CLOUD_OPS_CADENCE_POLL_SECONDS=30
NPCINK_CLOUD_RETENTION_CLEANUP_INTERVAL_SECONDS=3600
NPCINK_CLOUD_USAGE_ROLLUP_INTERVAL_SECONDS=3600
NPCINK_CLOUD_ROUTER_DIAGNOSTICS_INTERVAL_SECONDS=900
NPCINK_CLOUD_LATENCY_PROBE_INTERVAL_SECONDS=900
NPCINK_CLOUD_ALERT_PROVIDER_DEGRADATION_INTERVAL_SECONDS=900
NPCINK_CLOUD_PROVIDER_HEALTH_SCAN_INTERVAL_SECONDS=900
```

The internal operator summary endpoints:

- `GET /internal/service/ops/cadence`
- `GET /internal/service/observability/summary`

These now answer the minimum operator questions without adding a second control
surface:

- which cadence task is stale
- whether `worker`, `callback-worker`, and `ops-worker` are alive
- whether execution backlog or callback backlog is under pressure
- whether provider health freshness is stale and which providers are degraded
- whether OTLP tracing is wired to the configured external exporter endpoint

Production Compose does not bundle an OpenTelemetry Collector or Jaeger.
Ordinary runtime may leave `NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT` and
`NPCINK_CLOUD_OTEL_TRACE_QUERY_URL` empty. A formal release must configure both
against operator-owned observability infrastructure and prove that a fresh
Cloud trace is queryable. Starting a debug exporter is not release-complete
evidence.

Formal operator procedures now live in
[`deploy/OPS_PLAYBOOK.md`](deploy/OPS_PLAYBOOK.md).
Release readiness should now prefer `GET /health/operational-ready` over
`GET /health/ready`; the former enforces fresh worker heartbeats, fresh cadence
tasks, and fresh provider health in addition to DB/Redis reachability.

From the repository root you can also use:

```bash
pnpm run dev
pnpm run test
pnpm run lint
pnpm run build
pnpm run bundle
pnpm run deploy:ssh -- --ssh-host your-cloud-host
```

From the repository root, you can also run:

```bash
make router-performance
make router-diagnostics
make latency-probe
make alert-provider-degradation
```

## Deploy Bundle

Build a production bundle:

```bash
pnpm run bundle
```

Bundle contents:

- `docker-compose.prod.yml`
- `docker-compose.runtime.yml`
- `deploy/common.sh`
- `deploy/deploy-to-ssh-host.sh`
- `deploy/nginx.prod.conf`
- `deploy/remote-load-and-up.sh`
- `deploy/remote-migrate.sh`
- `deploy/remote-baseline-status.sh`
- `deploy/remote-seed-runtime.sh`
- `deploy/remote-smoke.sh`
- `dist/api.tar.gz`
- `dist/worker.tar.gz`

Remote phase helpers are not standalone bootstrap commands. Use
`deploy/deploy-to-ssh-host.sh`, which freezes the exact bundle and enforces the
only supported sequence: prepare images, stop/prove public and write services,
start data services, migrate with the staged image, activate the pointer, then
start API, workers, and traffic in separate proved batches. Directly invoking
`remote-load-and-up.sh` without an explicit governed phase is rejected.

`remote-smoke.sh` now expects `NPCINK_CLOUD_INTERNAL_AUTH_TOKEN` from the deploy
env file so it can verify `GET /health/ready`, `/docs`, `/redoc`, and internal
POST routes all respect the perimeter contract before it runs the public runtime
smoke.

`remote-smoke.sh` also now assumes the current public auth contract:

- `GET /v1/catalog/models` is a signed public read, not an anonymous endpoint
- the seeded smoke key must include `catalog:read` in addition to
  `runtime:resolve,runtime:execute,runtime:read,stats:read`
- if you override deploy/seed scopes manually, preserve `catalog:read` or the
  catalog portion of smoke will fail with `auth.scope_denied`

Remote SSH deploy from your local machine:

Every full deploy example below requires the signed-smoke HMAC secret in the
protected process environment. It is intentionally not accepted on argv and
is not read from `.env.deploy`. In an interactive shell, read it without echo
before invoking the deploy:

```bash
IFS= read -r -s NPCINK_CLOUD_SECRET
printf '\n'
export NPCINK_CLOUD_SECRET
```

```bash
pnpm run deploy:ssh -- \
  --ssh-host your-cloud-host \
  --ssh-user root \
  --remote-dir /opt/npcink-ai-cloud \
  --env-file .env.deploy \
  --site-id site_smoke \
  --key-id key_default
```

To also run the buyer-facing portal verification after the standard runtime smoke,
add `--with-portal-smoke` with an explicit site + member email. That extra post-step
runs real-site bootstrap plus `remote-portal-smoke.sh` on the fresh release:

```bash
pnpm run deploy:ssh -- \
  --ssh-host your-cloud-host \
  --ssh-user root \
  --remote-dir /opt/npcink-ai-cloud \
  --env-file .env.deploy \
  --with-portal-smoke \
  --site-id site_smoke \
  --member-email site-admin@example.com
```

To prove a specific provider was selected during remote smoke, pass explicit
expectations through the same deploy command:

```bash
pnpm run deploy:ssh -- \
  --ssh-host your-cloud-host \
  --ssh-user root \
  --remote-dir /opt/npcink-ai-cloud \
  --env-file .env.deploy \
  --site-id site_smoke \
  --key-id key_default \
  --profile-id text.balanced \
  --prompt-text "anthropic remote smoke request" \
  --expected-provider-id anthropic
```

After the deploy command finishes, remove the secret from the interactive
shell with `unset NPCINK_CLOUD_SECRET`.

Notes:

- `deploy-to-ssh-host.sh` builds the bundle by default, uploads
  `deploy-bundle.tgz` via `scp`, then runs
  `load -> migrate -> baseline-status -> seed -> smoke`
  over `ssh`.
- Formal production automation uses the `production` branch and
  `docker-compose.runtime.yml`; see
  [`deploy/PRODUCTION_GITHUB_DEPLOY.md`](deploy/PRODUCTION_GITHUB_DEPLOY.md).
- The recommended order is now fixed:
  `local code/docs -> local Docker/perimeter -> remote SSH deploy`.
  Do not use the remote host as the default inner-loop environment.
- If your default always-on machine is the office `mac mini`, you may use it as
  a deploy jump host, but keep the release path formal:
  `scripts/mini-cloud-deploy.sh -> deploy/deploy-to-ssh-host.sh`.
  Do not treat the mini dev compose stack as the production release path.
- `--env-file` is optional; when present it is copied to the remote release and
  exposed as `NPCINK_CLOUD_ENV_FILE` for the remote scripts.
- If `--env-file` is omitted but the current remote release already has
  `.env.deploy`, `deploy-to-ssh-host.sh` now carries that file forward into the
  new release automatically.
- `remote-smoke.sh` now accepts `--expected-provider-id`,
  `--expected-model-id`, `--expected-instance-id`, and `--prompt-text` so the
  off-machine smoke can prove which provider/model actually executed.
- `remote-provider-status.sh` prints provider configuration state, runtime
  registry presence, and catalog counts without revealing API keys. Use it
  before remote Anthropic/OpenAI smoke to confirm the target provider is
  actually registered.
- `remote-baseline-status.sh` is now the fixed remote schema/env gate. It fails
  fast if the remote release is not on the current Alembic head, if critical
  commercial/runtime tables or columns are missing, or if
  `NPCINK_CLOUD_INTERNAL_AUTH_TOKEN` is not actually visible inside the running
  `api` container.
- If remote deploy fails while local Docker checks still pass, suspect
  `.env.deploy`, persisted database drift, release carry-forward behavior, or
  provider reachability before suspecting the local source tree.
- Ad-hoc remote env mutation is retired. Supply the protected production env
  file to `deploy/deploy-to-ssh-host.sh`; configuration is applied only inside
  the same governed release transaction as exact image activation.
- Final off-machine deploy evidence still requires a real external host; this
  workspace currently records the active target in
  `deploy/WORKSPACE_TARGET.md`, but SSH user, base URL, and deploy env
  still need to be completed before the host is deploy-ready.

Remote model provider setup now happens through `/admin/ai-resources` after
deploy. Add or update the provider connection there, then use the masked
connection test before running provider-specific smoke.

```bash
ssh root@your-cloud-host 'cd /opt/npcink-ai-cloud/current && bash -s' \
  < deploy/remote-provider-status.sh
```

Local bundle replay using the exact deploy artifacts:

```bash
pnpm run check:e2e:deploy-bundle:smoke
```
