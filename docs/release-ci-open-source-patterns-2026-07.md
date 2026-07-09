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
- `master`, `main`, and `production` pushes still run the full backend gate.

This keeps PR feedback faster without weakening release branches.

### Timing as an artifact

Large CI systems treat timing data as release evidence instead of relying on
manual log reading. Cloud CI now emits:

- a run-level timing summary through `scripts/report-release-timing.py`;
- a pytest JUnit artifact for full backend push runs;
- a slow-test markdown summary through `scripts/report-junit-timing.py`.

The immediate goal is observability. Test splitting should be based on collected
slow-test evidence instead of guesses.

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

## Follow-Up Order

1. Collect several `pytest-backend-timing` artifacts from real `master` and
   `production` runs.
2. Identify the slowest backend test files and whether the long pole is setup,
   mypy, ruff, or pytest.
3. Split only the proven long pole:
   - start with pytest groups if pytest dominates;
   - split lint/type/test jobs only if bootstrap duplication still improves
     wall time.
4. Keep `production` deployment dependent on stable aggregate gates, not on
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
