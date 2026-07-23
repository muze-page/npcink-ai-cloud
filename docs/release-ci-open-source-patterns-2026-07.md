# Release CI Open-Source Patterns 2026-07

Status: active engineering note.

Purpose: record the release-flow patterns borrowed from mature open-source CI
practice and how they map to Npcink AI Cloud without expanding Cloud product
scope.

## Boundary

This note is only about CI, release verification, and timing observability.

It does not approve:

- a second Cloud control plane
- a second local ability or workflow registry
- new runtime orchestration infrastructure
- new product/admin/portal surfaces
- replacing operator judgment for QQ login, mailbox delivery, or real payment
  account validation

Cloud remains the hosted runtime enhancement layer. The pipeline may answer
"is this release mechanically safe enough to proceed" and "where did the time
go"; it must not become product governance truth.

## Patterns Borrowed

### Path-aware gates

Mature projects avoid running every expensive gate for every small change. The
current Cloud CI keeps that pattern:

- pull requests use a targeted backend gate by default;
- high-risk backend or release surfaces escalate to the full backend gate;
- `master`, `main`, and `production` pushes still run the full backend gate;
- the full backend gate is split into static checks and pytest shards only
  after scope classification says the full gate is required.

This keeps PR feedback faster without weakening release branches.

### Local iteration is narrower than CI

The path-aware PR workflow is an asynchronous repository gate. It does not
define the minimum command set for every local edit.

Use three local verification tiers:

| Tier | Typical scope | Local evidence |
|---|---|---|
| Feature-local | docs, copy, i18n, bounded UI, isolated module fix | focused regression tests, changed-file static checks, and one focused E2E only when interaction changed |
| Shared or high risk | public API/error contract, auth, database/migration, shared models/config, workers, dependencies, CI, containers, deploy, security | focused tests plus the relevant anti-drift, perimeter, or seam gate; full local suite only when needed for diagnosis |
| Integration/release | integration closeout, release candidate, `master`/`production`, cross-repository milestone | all applicable repository, release-policy, deploy, and cross-repository gates |

`pnpm run check:fast` currently means the complete contract and domain suites.
It is an integration gate despite its historical name, not the default local
gate for a small fix.

The targeted PR backend job currently still runs all of `tests/contract` before
running changed test files. That is broader than feature-local development and
must not be copied into every agent session. CI may retain this asynchronous
ratchet while its timing remains acceptable; local development stops after the
required risk tier passes.

### Timing as an artifact

Large CI systems treat timing data as release evidence instead of relying on
manual log reading. Cloud CI now emits:

- a run-level timing summary through `scripts/report-release-timing.py`;
- pytest JUnit artifacts for full backend shard runs;
- a slow-test markdown summary through `scripts/report-junit-timing.py`.

The immediate goal is observability. Test splitting is based on collected
slow-test evidence instead of guesses. `ci/pytest-backend-durations.json` stores
the current per-file duration weights generated from the production CI JUnit
artifact.

### Smoke automation with explicit human remainder

Production pushes now run a post-deploy preflight after the deploy job succeeds.
The preflight covers public service health, protected admin access, and the
safe public Alipay callback posture.

Formal release smoke runs automatically only when the corresponding GitHub
Actions secrets are configured. If they are missing, CI records the skip in the
job summary instead of printing secrets or blocking every deploy.

QQ login, mailbox delivery, and real Alipay account/payment confirmation remain
operator-tested because they depend on external accounts and provider state.

### Aggregate checks before more shards

Before adding pytest shard jobs, keep one stable required result name for the
release gate. When the backend suite is split, add a stable aggregate job that
depends on all shards and make the aggregate the required check. This prevents
branch protection from depending on changing shard names.

Cloud CI now follows this shape: `backend-scope` decides targeted versus full
backend, `backend-targeted` handles the cheap PR path, `backend-static` runs
anti-drift/Ruff/Mypy for the full path, `backend-pytest` runs three weighted
pytest shards, and the stable `backend` job aggregates the result for deploys
and branch protection.

## Follow-Up Order

1. Track the targeted PR contract-suite duration separately; split or select
   contract files only if its observed latency becomes the PR feedback
   bottleneck.
2. Refresh `ci/pytest-backend-durations.json` from several successful
   `pytest-backend-timing-shard-*` artifacts after the new split has run.
3. Compare actual wall time for `backend-static` and the three pytest shards
   against the previous 7-8 minute monolithic backend gate.
4. Rebalance shard count only if one shard remains the long pole for several
   releases.
5. Keep `production` deployment dependent on stable aggregate gates, not on
   individual shard names.

## References

- FastAPI GitHub Actions test workflow:
  `https://github.com/fastapi/fastapi/blob/master/.github/workflows/test.yml`
- Sentry GitHub Actions workflows:
  `https://github.com/getsentry/sentry/tree/master/.github/workflows`
- pytest-split duration-based grouping:
  `https://github.com/jerry-git/pytest-split`
- GitHub Actions job summaries:
  `https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions#adding-a-job-summary`
