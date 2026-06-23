# Internal Alpha Execution Plan

Status: active internal plan
Date: 2026-05-28
Scope: local development, mini/remote preview, and pre-release Cloud validation

## Purpose

This plan records the next execution order while Npcink AI Cloud is still under
local development and has no external users.

The current objective is not GA release, not a customer-facing commercial front
office, and not a broader admin/observability build-out. The objective is to
prove the core AI capability loop:

`local plugin -> Cloud API key -> hosted GPT5.5 request -> worker execution -> result callback -> minimum usage/error evidence`

## Focus Reset - 2026-06-06

Current main target: core hosted AI capability, starting with GPT5.5 text.

Reason:

- The product needs a clear user-facing AI capability before more operator
  surfaces add value.
- Free or near-free GPT5.5 is useful only if users can reliably use it through
  the normal toolbox/runtime path.
- Admin governance, cadence rollups, dashboards, and sorting are now treated as
  a minimum safety layer, not the main development direction.

Completion signal:

- A normal user path can trigger a hosted GPT5.5 text request and receive the
  result without operator intervention.
- Provider timeout, HTTP failure, invalid response, entitlement rejection, and
  callback failure produce readable minimum errors.
- The run writes enough usage/error evidence for support and cost safety, but
  no new admin page, report, control plane, or governance workflow is required.

Paused until the core loop is proven:

- new admin governance pages
- richer governance alert ranking
- dashboard/report/export work
- multi-model expansion beyond the next capability needed by the user path
- commercial front-office work

## Boundary

Cloud remains the runtime and service enhancement layer for the local Magick AI
plugin.

Allowed in this plan:

- hosted runtime execution
- provider configuration and health checks
- queue-backed worker execution
- usage, billing, entitlement, and audit detail
- bounded `/admin/*` operator surfaces
- bounded `/portal/*` user workspace surfaces
- local, mini, or preview environment smoke verification

Not in this plan:

- checkout, payment, invoice, or dunning front office
- seat lifecycle productization
- GA customer portal or self-serve onboarding
- Cloud skill registry, MCP platform, router editor, prompt editor, or workflow truth
- Temporal, Celery, Kafka, Kubernetes-first deployment, or a second scheduler truth

## Priority Matrix

| Work item | Impact | Difficulty | Unlocks later work | Decision |
| --- | --- | --- | --- | --- |
| Core GPT5.5 hosted text loop | High | Medium | Yes | Main target |
| Current branch and validation baseline | High | Low | Yes | Keep as support work |
| Minimum runtime error/usage evidence | High | Medium | Yes | Do only as needed by the core loop |
| Internal alpha end-to-end loop | High | Medium | Yes | Keep, but narrow to the user AI path |
| Bounded frontend polish | Medium | Medium | No | Do only when it improves the core user path |
| Admin governance and dashboards | Low for current phase | Medium | No | Pause after current safety baseline |
| Customer-facing commercial front office | Low for current phase | High | No | Defer |
| Heavy orchestration or new infrastructure | Negative for current phase | High | No | Do not start |

## Main Target

Current main target: core hosted GPT5.5 text loop inside the internal alpha path.

Reason:

- There are no external users yet.
- The highest risk is not missing front-office or admin features; it is whether
  users can actually invoke the hosted AI capability through the intended path.
- A working GPT5.5 text loop gives concrete evidence for the next capability
  expansion.

Completion signal:

- A local or mini environment can complete the narrow core path:
  `provider configured -> API key -> WordPress/addon toolbox trigger -> signed hosted GPT5.5 runtime request -> callback/result visible -> minimum usage/error evidence`.
- `GET /health/operational-ready` reports ready in the target environment.
- Worker heartbeat, provider health, runtime diagnostics, and usage state are inspectable.
- Failure modes identify the broken layer: provider, auth, worker, callback, entitlement, billing, or environment config.

## Execution Order

### Step 1: Current Branch And Validation Baseline

Goal:

- Make the current development branch understandable and repeatably verifiable before adding or fixing behavior.

Recommended actions:

1. Inspect branch status and local untracked files.
2. Decide whether generated artifacts such as `frontend/test-results/` should be removed, ignored, or preserved outside the commit.
3. Run the smallest validation lanes that match the current repo state.
4. Record failures as specific follow-up tasks rather than mixing unrelated cleanup into feature work.

Suggested command order from the repository root:

```bash
git status --short --branch
pnpm run check:fast
pnpm run check:seam
pnpm run frontend:type-check
pnpm run frontend:lint
```

If a command is unavailable or stale because scripts were renamed, use the
current `package.json` script name with the same intent:

- contract/domain baseline
- API/perimeter seam baseline
- frontend type check
- frontend lint

Completion signal:

- Branch status is understood.
- Generated local artifacts are not accidentally included.
- Baseline commands either pass or produce a short, categorized failure list.

Current record:

- [Internal Alpha Baseline - 2026-05-28](internal-alpha-baseline-2026-05-28.md)

### Step 2: Internal Alpha Environment

Goal:

- Stand up a local, mini, or preview target that behaves like a real internal alpha environment.

Minimum inputs:

- one test WordPress site
- one Cloud base URL
- one Portal public base URL
- local or preview TLS/trusted-host posture as appropriate
- test SMTP or an explicit development-code path for non-release alpha verification
- one provider credential suitable for real hosted runtime smoke
- one Cloud API key saved into the WordPress Cloud addon

Completion signal:

- Admin, Portal, addon, provider, and runtime paths all point at the same target environment.

Current local target:

- Cloud base URL: `http://127.0.0.1:8010`
- Portal public base URL: `http://127.0.0.1:8010`
- WordPress site: `https://npcink.local/`
- WordPress addon settings path:
  `https://npcink.local/wp-admin/admin.php?page=npcink-cloud-addon`
- Portal login path for local alpha: `/portal/dev-entry`
- Local dev-entry origin allowlist:
  `http://127.0.0.1:8010,http://localhost:8010`
- Provider target: DeepSeek through the OpenAI-compatible adapter

Done:

- Local Cloud Docker stack is running.
- `callback-worker` is part of the local Docker Compose stack.
- Deterministic pytest entrypoints clear OpenAI-compatible API key environment
  variables so local real-provider credentials do not leak into baseline tests.
- Cloud site/key/site-admin/subscription baseline is seeded for
  `site_npcink_local`.
- WordPress Cloud addon is saved and verified against the local Cloud base URL.
- Portal dev-entry login works and shows the bound WordPress site.
- DeepSeek API credentials are configured locally.
- Real provider catalog and health scan work for `deepseek-v4-flash`.
- Public signed runtime execution against `deepseek-v4-flash` succeeded with
  `fallback_used=false`.

Blocked for real provider smoke:

- None for the local DeepSeek smoke path.
- Continue to keep the key local-only and out of git.

### Step 3: Pre-Release Smoke Rehearsal

Goal:

- Use the formal smoke scripts as an alpha rehearsal without calling the system GA-ready.

Recommended actions:

1. Run the local or remote smoke path against the chosen target.
2. Capture failures by layer.
3. Fix repository code/config defaults only when the failure is reproducible from repo state.
4. Keep host-only secret or environment gaps in an operator checklist.

Completion signal:

- The smoke path proves health, auth, portal login, admin login, the WordPress
  addon configuration/read path, and one signed runtime request.

Current local result:

- `pnpm run smoke:local-alpha` passed against:
  - Cloud: `http://127.0.0.1:8010`
  - WordPress: `https://npcink.local/`
  - Provider/model: DeepSeek via OpenAI-compatible adapter, `deepseek-v4-flash`
- Evidence is written under `.tmp/local-alpha-smoke/` and intentionally excludes
  secrets.
- The current Cloud contract intentionally keeps `/v1/addon/*` projection routes
  absent. Local addon verification is therefore done through the WordPress Cloud
  addon admin tab plus Cloud entitlement/runtime/usage APIs.

Current onboarding contract:

- `pnpm run smoke:internal-alpha-onboarding` verifies the fast Admin to Portal
  onboarding path in an isolated API test database.
- The path covers `platform_admin` account/package/subscription setup,
  `site_admin` Portal login, site-admin-created site binding, site-admin-issued Cloud API key,
  one signed runtime request, usage meter evidence, Admin/Portal audit
  visibility, and `trial_readiness.status == ready`.
- This is a contract smoke for the Cloud service boundary; it does not replace
  the full local `smoke:local-alpha` run against Docker Compose and WordPress.

### Step 4: Runtime And Ops Minimum Hardening

Status: **基础完成** (runtime/operator drill baseline stable)

Goal:

- Improve the parts that alpha smoke exposes as fragile.

Preferred scope:

- abuse guard explainability
- queued/running lease recovery minimum behavior
- worker and callback diagnostics
- provider health visibility
- operator-readable runtime failure classification

Do not introduce a new orchestration engine or scheduler truth for this step.

Current hardening pass:

- Runtime diagnostics now include a `failures` block with recent failed runs,
  recent provider error calls, top runtime error codes, top provider errors, and
  the dominant error stage.
- Runtime diagnostics now include `operator_guidance` with the primary blocker,
  evidence path, and bounded suggested actions.
- The guidance keeps diagnosis inside the existing Cloud service-plane evidence:
  callback, queue, cancel, runtime failures, provider failures, and retention.
- `pnpm run drill:provider-failure` verifies provider-stage guidance with an
  isolated fake provider and temporary database. It does not use real provider
  credentials.
- `pnpm run drill:callback-failure` verifies callback delivery guidance with an
  isolated fake provider, registered site callback metadata, and a failing
  callback dispatcher. It does not call the real provider or WordPress.
- Operator checklist added at [docs/internal-alpha-operator-checklist.md](internal-alpha-operator-checklist.md).
  It maps `operator_guidance.primary_reason` to bounded operator actions without
  introducing a new control plane.

### Step 5: Bounded Frontend Polish

Status: **已完成第一轮**

Goal:

- Improve admin/portal usability after the service chain is proven.

Candidate work:

- Usage page charts
- retry hook integration where data fetching currently uses manual reloads
- mobile navigation verification
- progressive loading on data-heavy pages
- bounded report export only if it remains detail/read-only

Current polish pass:

- Portal Usage page now integrates `UsageChart` with `today` and `rolling_24h` windows
  for requests, tokens, and cost trends.
- `/portal/usage` data fetching now uses the existing `useRetry` hook for initial
  load, site switch, and error retry.
- Mobile layout verification added to `/portal/usage`, `/portal`, and
  `/admin/sites/{siteId}` via existing e2e paths.

## Deferred Work

The following remain intentionally deferred until a separate boundary decision:

- checkout/payment/invoice/dunning
- full customer commercial front office
- seat lifecycle productization
- GA customer portal and self-serve onboarding
- Cloud-owned skills/MCP/router/prompt/workflow control planes
- heavy orchestration infrastructure
