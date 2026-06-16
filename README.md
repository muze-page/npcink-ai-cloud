# Magick AI Cloud

Hosted Model Runtime for Magick AI.

Magick AI Cloud is the runtime enhancement layer for the local Magick AI plugin.
It is not a second control plane, a second source of truth, or a SaaS
replacement for the plugin.

## Scope Reminder

Magick AI Cloud is the runtime enhancement layer for the local Magick AI plugin.
It is not a second control plane, a second source of truth, or a SaaS
replacement for the plugin.

Current focus lock:

- main target: prove the user-facing hosted GPT5.5 text loop through the normal
  runtime/toolbox path
- keep only minimum usage, error, and provider evidence needed to support that
  loop
- pause new admin governance pages, dashboards, reports, alert-ranking
  expansion, and commercial front-office work until the core AI path is proven
- do not add new orchestration infrastructure or move local plugin truth into
  Cloud

Current repository status is a strong-contraction cleanup baseline:
- orchestration, task-packs, prompt/preset advisor, and portal thick features
  have been removed
- admin surface is bounded to accounts, sites, plans, subscriptions, billing
  inspect, provider ops, runtime diagnostics, audit, and commercial decisions
- portal surface is bounded to login, session, sites, keys, usage, entitlements,
  billing, and audit
- addon projection/repair surfaces are not part of this baseline; they remain
  deferred to a separate proposal with independent review

Operational references:

- [deploy/OPS_PLAYBOOK.md](deploy/OPS_PLAYBOOK.md)
- [deploy/RELEASE_CHECKLIST.md](deploy/RELEASE_CHECKLIST.md)
- [deploy/PROJECTION_DRILL_EVIDENCE_2026-04-15.md](deploy/PROJECTION_DRILL_EVIDENCE_2026-04-15.md)
- [docs/internal-alpha-execution-plan.md](docs/internal-alpha-execution-plan.md)
- [docs/internal-alpha-operator-checklist.md](docs/internal-alpha-operator-checklist.md)
- [docs/internal-alpha-onboarding-smoke-runbook.md](docs/internal-alpha-onboarding-smoke-runbook.md)
- [docs/external-trial-capability-note-2026-06-10.md](docs/external-trial-capability-note-2026-06-10.md)
- [docs/external-trial-readiness-checklist-2026-06-10.md](docs/external-trial-readiness-checklist-2026-06-10.md)
- [docs/external-trial-operator-runbook-2026-06-11.md](docs/external-trial-operator-runbook-2026-06-11.md)
- [docs/external-trial-copy-and-log-2026-06-11.md](docs/external-trial-copy-and-log-2026-06-11.md)
- [docs/external-trial-record-magick-ai-local-2026-06-10.md](docs/external-trial-record-magick-ai-local-2026-06-10.md)
- [docs/external-trial-user-briefing-copy-zh-2026-06-10.md](docs/external-trial-user-briefing-copy-zh-2026-06-10.md)
- [docs/external-trial-handoff-summary-2026-06-15.md](docs/external-trial-handoff-summary-2026-06-15.md)
- [docs/nightly-inspection-real-site-operator-trial-2026-06-17.md](docs/nightly-inspection-real-site-operator-trial-2026-06-17.md)
- [docs/cloud-adapter-analysis-contract.md](docs/cloud-adapter-analysis-contract.md)
- [docs/cloud-local-integration-and-rebuild-guidance.md](docs/cloud-local-integration-and-rebuild-guidance.md)
- [docs/cloud-content-generation-boundary-v1.md](docs/cloud-content-generation-boundary-v1.md)
- [docs/cloud-bulk-article-run-v1.md](docs/cloud-bulk-article-run-v1.md)
- [docs/nightly-site-inspection-morning-brief-v1.md](docs/nightly-site-inspection-morning-brief-v1.md)
- [docs/cloud-agent-positioning-v1.md](docs/cloud-agent-positioning-v1.md)
- [docs/cloud-agent-feedback-contract-v1.md](docs/cloud-agent-feedback-contract-v1.md)
- [docs/internal-ai-advisor-v1.md](docs/internal-ai-advisor-v1.md)
- [docs/writing-assistance-evidence-history-2026-06.md](docs/writing-assistance-evidence-history-2026-06.md)

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
- local portal real-site bootstrap: `pnpm run portal:bind:dev -- --site-id <site-id> --member-email <email>`
- scaffold one new Cloud route pack: `pnpm run scaffold:route -- --route-id <route-id>`
- scaffold one new Portal route pack: `pnpm run scaffold:portal-route -- --route-id <route-id>`
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
`magick_ai_cloud.egg-info/**` are not source truth. They are local setuptools
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

Model operations admin surfaces (provider connections, model intelligence,
recognition review, and platform model ops console) have been removed.
`catalog/platform-models` is retained only as runtime metadata, not as a
platform model operations console.

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
  - bounded `/admin` session cookie login via `internal token`
  - accounts, sites, plans, subscriptions, runtime diagnostics, audit, and commercial decisions
- bounded portal auth seam is now landed for:
  - invited `user` email verification-code login
  - cookie-backed `/portal/*` member session
  - account/site-scoped read-only portal workspace for sites, keys, usage, billing, and audit

Still deferred in the current phase:

- stronger app-side abuse guard beyond the current minimal request/replay
  protections and cooldown windows
- richer long-window anomaly / burst heuristics and support-bundle/export grade
  operator explainability beyond the current bounded runtime pressure diagnostics
  and bounded abuse watchlists
- broader queued/running lease recovery beyond the current queue-backed runtime
  worker plus callback dispatch stale-lease reclaim
- customer-facing commercial front-office still remains deferred:
  - seat lifecycle
  - checkout/payment
  - invoice/reconciliation
  - dunning-grade customer billing front-office
- richer platform admin directory/session inventory remains deferred

Commercial acceptance freeze:

- `plans + plan_versions` remain the only package execution truth
- `free / pro / agency` remain tier templates
- `plan_free / plan_free_v1` is the explicit production free package
- `Free / Pro / Agency` remain the only current package presentation aliases
- points are presentation, not a ledger
- operator top-up means current billing period budget headroom only
- no wallet, no permanent credit, no customer self-serve buy flow in the current phase
- `plan_dev_unlimited / plan_dev_unlimited_v1` remain dev-only bootstrap/runtime baselines, not production free packaging

## Validation Ladder

Cloud development and verification now follow a fixed three-layer order:

1. Local source workspace:
   - edit `app/**`, `frontend/**`, `tests/**`, contracts, and feature docs here first
   - this remains the only day-to-day development truth
2. Local Docker runtime:
   - validate the current branch with `docker-compose.dev.yml`, focused `pytest`,
     and `pnpm run check:perimeter`
   - this is the default runtime test loop for auth, perimeter, worker, and
     bundle-adjacent behavior
3. Remote host deploy verification:
   - use `deploy-to-ssh-host.sh` only after local checks pass
   - remote hosts exist to prove `scp -> load/up -> migrate -> seed -> smoke`,
     real provider readiness, and real persisted-state compatibility
   - they do not replace the local development loop or become a second source
     of truth

Remote hosts are therefore release-verification surfaces, not the primary
authoring environment. If a problem appears only after SSH deploy, treat it as
deploy/config/state drift to be fixed back in the repo, not as a reason to move
daily development onto the host.

## Borrowed Foundations

Cloud should keep borrowing mature infrastructure patterns instead of growing
bespoke second-truth systems:

- tracing and trace export stay on OpenTelemetry:
  - FastAPI request spans, `traceparent`, OTLP export, and the trace-sink seam
    already use OTel
  - prefer extending this path rather than inventing a custom trace protocol or
    local-only telemetry format
- bounded kill switches should go through one env-backed feature-flag seam:
  - `MAGICK_CLOUD_FEATURE_FLAGS_JSON` is the current lightweight override path
  - it is intentionally read-only/runtime-only and does not create a new DB
    registry or customer-visible control plane
  - observability summary now reports the effective flag set and override count
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
POSTGRES_PASSWORD='prod-password-32-characters-secret' \
MAGICK_CLOUD_DATABASE_URL='postgresql+psycopg://magick:prod-password-32-characters-secret@postgres:5432/magick_ai_cloud' \
docker compose -f docker-compose.prod.yml config >/dev/null
docker build -t magick-cloud-prod-check -f Dockerfile .
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

Use the worker profiles only when the current task needs them:

```bash
pnpm run dev:runtime   # adds the queued runtime worker
pnpm run dev:callback  # adds runtime and callback workers
pnpm run dev:ops       # adds runtime, callback, and ops cadence workers
```

Keep local-only debug credentials such as `MAGICK_CLOUD_INTERNAL_AUTH_TOKEN`,
`MAGICK_CLOUD_ADMIN_BOOTSTRAP_TOKEN`, `MAGICK_CLOUD_ADMIN_SESSION_SECRET`, and
`MAGICK_CLOUD_PORTAL_JWT_SECRET` in `.env.local` for dev Docker runs.
`.env.local` is gitignored, while production-style deploy helpers read
`.env.deploy` instead.

Runtime catalog metadata can also include Ollama-sourced model records in two modes:

- self-hosted/local node allowlist:
  - `MAGICK_CLOUD_OLLAMA_BASE_URL=http://host.docker.internal:11434`
  - `MAGICK_CLOUD_OLLAMA_MODEL_ALLOWLIST=llava:13b,bge-m3:latest`
- official Ollama cloud catalog:
  - `MAGICK_CLOUD_OLLAMA_BASE_URL=https://ollama.com`
  - `MAGICK_CLOUD_OLLAMA_API_KEY=<optional api key>`
  - `MAGICK_CLOUD_OLLAMA_CATALOG_ENABLED=true`
  - `MAGICK_CLOUD_OLLAMA_CATALOG_LIMIT=250`

The allowlist mode is best for private nodes you actually run. Ollama metadata is consumed as runtime catalog input only; it does not create a platform model operations surface.

For production-style remote deploys, start from [.env.example](.env.example),
then copy it to `.env.deploy` or another deploy env file. Production-style
config now fails fast when these are missing:

- `MAGICK_CLOUD_INTERNAL_AUTH_TOKEN`
- `MAGICK_CLOUD_ADMIN_BOOTSTRAP_TOKEN`
- `MAGICK_CLOUD_ADMIN_SESSION_SECRET`
- `MAGICK_CLOUD_PORTAL_JWT_SECRET`
- `MAGICK_CLOUD_PORTAL_PUBLIC_BASE_URL`
- `MAGICK_CLOUD_PORTAL_EMAIL_SMTP_HOST`
- `MAGICK_CLOUD_PORTAL_EMAIL_FROM_EMAIL`

Additional hardening rules now enforced:

- production API runs behind `gunicorn` + `uvicorn.workers.UvicornWorker`
- admin bootstrap auth is a separate secret from internal service auth outside development/test
- browser same-origin checks use explicit origin allowlists and fail closed on bad forwarded origin input
- trusted host / forwarded host validation no longer assumes ingress is always configured correctly
- callback registration and dispatch only accept `https://` targets that resolve to public IP space
- `MAGICK_CLOUD_DEBUG_LOCAL_ORIGIN_ALLOWLIST` defaults to empty and only applies in `development` / `test`

## Release Smoke

Before a formal deploy, run the combined release smoke:

```bash
bash deploy/release-smoke.sh \
  --base-url https://cloud.example.com \
  --internal-auth-token "$MAGICK_CLOUD_INTERNAL_AUTH_TOKEN" \
  --admin-token "$MAGICK_CLOUD_ADMIN_BOOTSTRAP_TOKEN" \
  --member-email invited-admin@example.com \
  --login-code 123456
```

The release smoke verifies:

- `GET /health/live`
- `GET /health/ready` with `X-Magick-Internal-Token`
- `GET /`
- `GET /portal/login`
- `POST /portal/v1/auth/code/request`
- `POST /portal/v1/auth/code/verify`
- `GET /portal/v1/session`
- `GET /admin/login`
- `POST /admin/auth/bootstrap`
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
- defaults to `*/5 * * * *`, configurable via `MAGICK_CLOUD_WP_CRON_SCHEDULE`

Remove it with:

```bash
source deploy/workspace-target.env.sh
pnpm run wp-cron:ssh -- remove
```

Platform identity/admin roadmap:

- current identity layering and third-party recommendation:
  [cloud-identity-system-overview-and-roadmap.md](../../magick-ai/docs/archive/plans/cloud-identity-system-overview-and-roadmap.md)
- current bounded read-only admin surface:
  [cloud-admin-mvp-plan.md](../../magick-ai/docs/archive/plans/cloud-admin-mvp-plan.md)
- current invite-only onboarding hardening slice:
  [cloud-invite-only-onboarding-v1-1-plan.md](../../magick-ai/docs/archive/plans/cloud-invite-only-onboarding-v1-1-plan.md)
- current member invite/login operator checklist:
  [cloud-portal-member-invite-flow-checklist.md](../../magick-ai/docs/archive/plans/cloud-portal-member-invite-flow-checklist.md)
- recommended platform super-admin plus controlled impersonation direction:
  [cloud-platform-admin-and-impersonation-plan.md](../../magick-ai/docs/archive/plans/cloud-platform-admin-and-impersonation-plan.md)
- current platform role contract:
  [cloud-platform-admin-role-model-v1.md](../../magick-ai/docs/contracts/cloud-platform-admin-role-model-v1.md)

Health endpoints:

- `GET /health/live`
- `GET /health/ready` with `X-Magick-Internal-Token`

If you need `/internal/*` routes in dev or prod, set
`MAGICK_CLOUD_INTERNAL_AUTH_TOKEN`. Internal routes fail closed when the token is
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
- production deploys should set:
  - `MAGICK_CLOUD_PORTAL_JWT_SECRET`
  - `MAGICK_CLOUD_PORTAL_PUBLIC_BASE_URL`
  - SMTP sender settings for verification-code delivery
Platform admin bootstrap auth:

- Cloud now assumes one non-self-serve `platform_admin`
- current bounded bootstrap path:
  - `POST /admin/auth/bootstrap`
  - request body: `{"token":"<admin bootstrap token>"}`
  - response establishes `magick_admin_session_token`
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
- platform-admin bootstrap uses the configured single platform admin reference
  and does not require a separate identity-provisioning surface
- current operator runbook for lean validation:
  - [cloud-platform-login-and-invite-runbook.md](../../magick-ai/docs/archive/plans/cloud-platform-login-and-invite-runbook.md)
Buyer-facing web routes:

- `GET /`
- `GET /portal/login`
- `GET /portal`
- `GET /portal/sites`
- `GET /portal/keys`
- `GET /portal/usage`
- `GET /portal/billing`
- `GET /portal/audit`
- `GET /portal/logout`

These routes are a bounded Cloud service status and portal layer, not a
customer-facing commercial front-office. Marketing pages, top-up catalog pages,
impersonation pages, compliance pages, and request queues are intentionally
removed.

## Verification Quickstart

For the fastest local verification loop:

1. Configure local portal auth in `.env`:
   - `MAGICK_CLOUD_PORTAL_JWT_SECRET=dev-portal-jwt-secret-with-at-least-thirty-two-bytes`
   - `MAGICK_CLOUD_PORTAL_PUBLIC_BASE_URL=http://127.0.0.1:8010`
2. Start local Cloud:
   - `pnpm run dev`
   - optional frontend auto-sync loop: `pnpm run frontend:watch`
3. Prefer binding Portal to one already provisioned real site:
   - `pnpm run portal:bind:dev -- --site-id <site-id> --member-email <email>`
4. If the environment is empty, seed a runtime baseline and then bind Portal:
   - `pnpm run seed:smoke`
   - `pnpm run portal:bind:dev -- --site-id <site-id> --member-email <email>`

The real-site bootstrap path reuses:

- one already provisioned account + site + subscription
- current usage meter events and billing state for that site
- existing site keys, unless you explicitly pass `--issue-key`

The runtime seed command creates a minimal site + subscription baseline for
operator smoke, and does not create portal members or portal-facing sample data.

Primary local verification routes:

- `http://127.0.0.1:8010/portal/login`
- `http://127.0.0.1:8010/portal`
- `http://127.0.0.1:8010/portal/overview`
- `http://127.0.0.1:8010/portal/keys`

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

For the shortest command-only runbook, see
[cloud-mvp-ops-runbook.md](../../magick-ai/docs/archive/plans/cloud-mvp-ops-runbook.md).

For one current-state identity overview and recommended evolution path, see
[cloud-identity-system-overview-and-roadmap.md](../../magick-ai/docs/archive/plans/cloud-identity-system-overview-and-roadmap.md).

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
- `POST /admin/auth/bootstrap`
- `GET /admin/session`
- `GET /admin/logout`

Admin auth is bounded to the dedicated admin bootstrap token seam:

- `POST /admin/auth/bootstrap` with `token=<MAGICK_CLOUD_ADMIN_BOOTSTRAP_TOKEN>`
  establishes one bounded ops cookie session
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

- [cloud-admin-mvp-plan.md](../../magick-ai/docs/archive/plans/cloud-admin-mvp-plan.md)

Current internal admin routes:

- `GET /admin`
- `GET /admin/accounts`
- `GET /admin/accounts/{account_id}`
- `GET /admin/sites`
- `GET /admin/sites/{site_id}`
- `GET /admin/subscriptions`
- `GET /admin/subscriptions/{subscription_id}`
- `GET /admin/login`
- `POST /admin/auth/bootstrap`
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
- provide the current `MAGICK_CLOUD_ADMIN_BOOTSTRAP_TOKEN`
- the page sets one bounded admin cookie session for `/admin`

This remains an internal runtime/operations surface. It is not a customer portal
and not a second control plane.

In production-style deploys, the bundled proxy forwards `/admin` and `/admin/*`
as the only public platform-admin surface. Legacy `/ops/*` paths are removed.

Current acceptance receipt:
[cloud-mvp-acceptance-receipt-2026-03-23.md](../../magick-ai/docs/archive/plans/cloud-mvp-acceptance-receipt-2026-03-23.md)

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
- set `MAGICK_CLOUD_PORTAL_PUBLIC_BASE_URL` when email links must point at the
  external customer-facing domain instead of the direct request host
- for SMTP delivery, configure:
  - `MAGICK_CLOUD_PORTAL_EMAIL_SMTP_HOST`
  - `MAGICK_CLOUD_PORTAL_EMAIL_SMTP_PORT`
  - `MAGICK_CLOUD_PORTAL_EMAIL_SMTP_USERNAME`
  - `MAGICK_CLOUD_PORTAL_EMAIL_SMTP_PASSWORD`
  - `MAGICK_CLOUD_PORTAL_EMAIL_SMTP_USE_SSL`
  - `MAGICK_CLOUD_PORTAL_EMAIL_SMTP_USE_STARTTLS`
  - `MAGICK_CLOUD_PORTAL_EMAIL_FROM_EMAIL`
  - `MAGICK_CLOUD_PORTAL_EMAIL_FROM_NAME`
  - `MAGICK_CLOUD_PORTAL_EMAIL_REPLY_TO`

For Alibaba Cloud enterprise mailbox, point the SMTP settings above at the
SMTP host/port and SSL or STARTTLS mode provided by your mailbox admin panel.
This keeps Cloud generic while still supporting Aliyun enterprise mail as the
actual sender.
For Aliyun-specific deploys, keep the concrete SMTP values in the chosen deploy
env file rather than committing provider-specific secrets.

Portal email self-test:

- `POST /internal/portal/email/test`
- requires `X-Magick-Internal-Token` and `Idempotency-Key`
- request body:

```json
{"recipient_email":"you@example.com"}
```

- example:

```bash
curl -X POST http://127.0.0.1:8000/internal/portal/email/test \
  -H "Content-Type: application/json" \
  -H "X-Magick-Internal-Token: ${MAGICK_CLOUD_INTERNAL_AUTH_TOKEN}" \
  -H "Idempotency-Key: portal-email-test-001" \
  -d '{"recipient_email":"you@example.com"}'
```

Provider execution modes:

- default: sample mode, no external provider calls
- set `MAGICK_CLOUD_OPENAI_API_KEY` to enable real OpenAI-compatible
  HTTP execution for `chat_completions / responses / embeddings`
- set `MAGICK_CLOUD_ANTHROPIC_API_KEY` to enable real Anthropic HTTP execution
  for text-only `messages`
- set `MAGICK_CLOUD_LITELLM_PROVIDER_ENABLED=true` with
  `MAGICK_CLOUD_LITELLM_BASE_URL` to enable LiteLLM Gateway as a hosted
  provider source
- set `MAGICK_CLOUD_VLLM_PROVIDER_ENABLED=true` with
  `MAGICK_CLOUD_VLLM_BASE_URL` to enable a self-hosted vLLM OpenAI-compatible
  provider
- set `MAGICK_CLOUD_TEI_PROVIDER_ENABLED=true` with
  `MAGICK_CLOUD_TEI_BASE_URL` and `MAGICK_CLOUD_TEI_MODEL_IDS` to enable a
  self-hosted TEI embedding provider
- set `MAGICK_CLOUD_OPENROUTER_PROVIDER_ENABLED=true` with
  `MAGICK_CLOUD_OPENROUTER_API_KEY` to enable OpenRouter as a hosted provider

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
- public signed `POST` 额外要求 `X-Magick-Nonce`
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

- `X-Magick-Internal-Token`
- `Idempotency-Key` on POST
- repeated internal POST replay markers are rejected as `auth.replay_blocked`
- not interchangeable with the public runtime HMAC headers
- also required for `GET /health/ready`

Catalog query extras:

- `GET /v1/catalog/models?recommended_for=text.balanced`
- response payloads include `recommended_sets` for the default hosted profiles

Deploy perimeter:

- `docker-compose.prod.yml` now ships a bundled perimeter proxy; only the proxy
  publishes the public port and the raw `api` container is no longer mapped to
  the host.
- Keep `/internal/*` behind allowlist or private ingress; the bundled proxy only
  forwards those paths for loopback/private callers and does not expose them as
  public routes.
- Keep `GET /health/ready` on the same internal/allowlisted path as
  `/internal/*`; only `GET /health/live` remains a minimal public liveness
  probe.
- Keep `/docs` and `/redoc` disabled in production.
- The bundled proxy adds only the minimum perimeter split and basic rate
  limiting. TLS termination, source restriction, IP allowlist, WAF, and stronger
  edge controls still depend on deployment.
- `remote-smoke.sh` also verifies `/docs`, `/redoc`, and internal POST fail
  closed without `X-Magick-Internal-Token`.

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
- each worker poll now drains up to `MAGICK_CLOUD_RUNTIME_WORKER_BATCH_SIZE`
  queued runs and up to `MAGICK_CLOUD_RUNTIME_CALLBACK_BATCH_SIZE` pending
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
  `MAGICK_CLOUD_RUNTIME_CALLBACK_WORKER_POLL_SECONDS`
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
- public signed POST requests must also carry `X-Magick-Nonce`; reused nonce
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
make env-ssh
```

`make deploy-smoke` currently reuses
`../magick-ai/tests/e2e/cloud-deploy-bundle-smoke-flow.sh` as a plugin-side e2e
test asset. This is a temporary test dependency for deploy verification only;
it does not move control-plane ownership, settings truth, or runtime authorship
back into the plugin workspace.

Example dev seed:

```bash
docker compose -f docker-compose.dev.yml run --rm api alembic upgrade head
docker compose -f docker-compose.dev.yml run --rm api python -m app.dev.seed_runtime \
  --site-id site_smoke \
  --key-id key_default \
  --secret magick-cloud-test-secret
```

Example real provider env:

```bash
export MAGICK_CLOUD_OPENAI_API_KEY=sk-...
export MAGICK_CLOUD_OPENAI_BASE_URL=https://api.openai.com/v1
export MAGICK_CLOUD_ANTHROPIC_API_KEY=sk-ant-...
export MAGICK_CLOUD_ANTHROPIC_BASE_URL=https://api.anthropic.com
export MAGICK_CLOUD_ANTHROPIC_VERSION=2023-06-01
```

If cross-arch Docker builds are unstable from your network, you can also export
optional pip mirror args before `make bundle` or `deploy-to-ssh-host.sh`:

```bash
export MAGICK_CLOUD_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export MAGICK_CLOUD_PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
```

With a real API key, `POST /internal/catalog/refresh` plus a valid
`X-Magick-Internal-Token`, and
`python -m app.workers.catalog_refresh` fetch `/models` from the configured
provider instead of using the built-in sample catalog. Anthropic is only added
to the runtime registry when `MAGICK_CLOUD_ANTHROPIC_API_KEY` is configured, so
an unconfigured sample adapter does not silently alter default routing.

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
`/wp-json/magick-ai/open/v1/router/performance-snapshot/callback`. This remains
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
`/wp-json/magick-ai/open/v1/router/diagnostics/callback`; otherwise it keeps
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
MAGICK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS=60
MAGICK_CLOUD_OPS_CADENCE_POLL_SECONDS=30
MAGICK_CLOUD_RETENTION_CLEANUP_INTERVAL_SECONDS=3600
MAGICK_CLOUD_USAGE_ROLLUP_INTERVAL_SECONDS=3600
MAGICK_CLOUD_ROUTER_DIAGNOSTICS_INTERVAL_SECONDS=900
MAGICK_CLOUD_LATENCY_PROBE_INTERVAL_SECONDS=900
MAGICK_CLOUD_ALERT_PROVIDER_DEGRADATION_INTERVAL_SECONDS=900
MAGICK_CLOUD_PROVIDER_HEALTH_SCAN_INTERVAL_SECONDS=900
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
- whether OTLP tracing is wired to the collector endpoint

Production-style compose now includes a minimal `otel-collector` sidecar using
[`deploy/otel-collector.config.yml`](deploy/otel-collector.config.yml).
By default, `MAGICK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT` points at
`http://otel-collector:4318/v1/traces` and the collector forwards to the
default Jaeger sink at `MAGICK_CLOUD_OTEL_TRACE_SINK_OTLP_ENDPOINT=jaeger:4317`.
`otel-collector debug exporter` no longer counts as release-complete state.

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
pnpm run env:ssh -- --ssh-host your-cloud-host
```

From `cloud/`, you can also run:

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

Remote bootstrap order:

```bash
tar xzf deploy-bundle.tgz
bash deploy/remote-load-and-up.sh
bash deploy/remote-migrate.sh
bash deploy/remote-baseline-status.sh
bash deploy/remote-seed-runtime.sh --site-id site_smoke --key-id key_default --secret magick-cloud-test-secret
bash deploy/remote-smoke.sh --base-url http://127.0.0.1:8010
```

`remote-smoke.sh` now expects `MAGICK_CLOUD_INTERNAL_AUTH_TOKEN` from the deploy
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

```bash
pnpm run deploy:ssh -- \
  --ssh-host your-cloud-host \
  --ssh-user root \
  --remote-dir /opt/magick-ai-cloud \
  --env-file .env.deploy \
  --site-id site_smoke \
  --key-id key_default \
  --secret magick-cloud-test-secret
```

To also run the buyer-facing portal verification after the standard runtime smoke,
add `--with-portal-smoke` with an explicit site + member email. That extra post-step
runs real-site bootstrap plus `remote-portal-smoke.sh` on the fresh release:

```bash
pnpm run deploy:ssh -- \
  --ssh-host your-cloud-host \
  --ssh-user root \
  --remote-dir /opt/magick-ai-cloud \
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
  --remote-dir /opt/magick-ai-cloud \
  --env-file .env.deploy \
  --site-id site_smoke \
  --key-id key_default \
  --secret magick-cloud-test-secret \
  --profile-id text.balanced \
  --prompt-text "anthropic remote smoke request" \
  --expected-provider-id anthropic
```

Notes:

- `deploy-to-ssh-host.sh` builds the bundle by default, uploads
  `deploy-bundle.tgz` via `scp`, then runs
  `load -> migrate -> baseline-status -> seed -> smoke`
  over `ssh`.
- The recommended order is now fixed:
  `local code/docs -> local Docker/perimeter -> remote SSH deploy`.
  Do not use the remote host as the default inner-loop environment.
- If your default always-on machine is the office `mac mini`, you may use it as
  a deploy jump host, but keep the release path formal:
  `scripts/mini-cloud-deploy.sh -> deploy/deploy-to-ssh-host.sh`.
  Do not treat the mini dev compose stack as the production release path.
- `--env-file` is optional; when present it is copied to the remote release and
  exposed as `MAGICK_CLOUD_ENV_FILE` for the remote scripts.
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
  `MAGICK_CLOUD_INTERNAL_AUTH_TOKEN` is not actually visible inside the running
  `api` container.
- If remote deploy fails while local Docker checks still pass, suspect
  `.env.deploy`, persisted database drift, release carry-forward behavior, or
  provider reachability before suspecting the local source tree.
- `env-to-ssh-host.sh` updates the remote release `.env.deploy` in place,
  carries the same values into the shared `/opt/magick-ai-cloud/.env.deploy`
  file, and restarts `api,worker` by default so new provider env takes effect
  immediately without a full redeploy.
- Final off-machine deploy evidence still requires a real external host; this
  workspace currently records the active target in
  `deploy/WORKSPACE_TARGET.md`, but SSH user, base URL, and deploy env
  still need to be completed before the host is deploy-ready.

Remote provider env sync example:

```bash
export MAGICK_CLOUD_ANTHROPIC_API_KEY=sk-ant-...
pnpm run env:ssh -- \
  --ssh-host your-cloud-host \
  --ssh-user root \
  --remote-dir /opt/magick-ai-cloud \
  --set MAGICK_CLOUD_ANTHROPIC_BASE_URL=https://api.anthropic.com \
  --set MAGICK_CLOUD_ANTHROPIC_VERSION=2023-06-01 \
  --from-env MAGICK_CLOUD_ANTHROPIC_API_KEY
```

After syncing env, confirm readiness before running Anthropic smoke:

```bash
ssh root@your-cloud-host 'cd /opt/magick-ai-cloud/current && bash -s' \
  < deploy/remote-provider-status.sh
```

Local bundle replay using the exact deploy artifacts:

```bash
pnpm run check:e2e:deploy-bundle:smoke
```
