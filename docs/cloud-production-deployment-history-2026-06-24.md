# Cloud Production Deployment History - 2026-06-24

Status: active operational history.

Scope: summarize the first production deployment of Npcink AI Cloud at
`https://cloud.npc.ink`, the GitHub-based release model, and the static legal
page deployment optimization. This is an operator and future-agent handoff
document, not a secret store.

## 1. Outcome

Npcink AI Cloud was deployed as a formal production service for
`https://cloud.npc.ink`.

The production posture is:

- run only production-required services on the cloud host;
- keep local development-only capabilities out of the production runtime;
- use Docker for runtime packaging and repeatable deployment;
- use GitHub as the source of truth for production code and policy changes;
- keep runtime secrets on the server or in GitHub secrets, not in repository
  files;
- continue treating Cloud as the hosted runtime enhancement layer, not a second
  WordPress control plane.

Verified public endpoints during this rollout included:

- `GET https://cloud.npc.ink/health/live`
- `GET https://cloud.npc.ink/terms`
- `GET https://cloud.npc.ink/terms/en/terms.html`
- `GET https://cloud.npc.ink/terms/zh/terms.html`
- `GET https://cloud.npc.ink/terms/styles.css`

## 2. Production Runtime Shape

Production uses the low-memory Docker runtime shape. The intended cloud host is
small in the current validation phase, so the production deployment excludes
local development sidecars and development-only workflows.

The production runtime is expected to include only production services such as:

- API service;
- frontend service;
- worker processes needed for production runtime behavior;
- PostgreSQL;
- Redis;
- internal proxy;
- Caddy for public HTTP/HTTPS.

The server-side deployment reuses an existing server `.env.deploy` rather than
embedding runtime secrets into GitHub or the source tree.

## 3. HTTPS, Domain, SMTP, And Provider Configuration

The public production origin is:

```text
https://cloud.npc.ink
```

HTTPS is owned by the production reverse-proxy setup. Production smoke checks
must use the public HTTPS origin, not the raw server IP or an internal Docker
port.

SMTP and model-provider configuration were treated as production runtime
configuration and copied/reused through server-side environment configuration.
The SMTP values discussed during setup were:

```text
SMTP host: smtp.qiye.aliyun.com
SMTP port: 465
SMTP username/from mailbox: auth@npc.ink
SMTP password: server-side secret, intentionally not recorded here
```

Do not commit SMTP passwords, provider API keys, internal auth tokens, session
secrets, database passwords, or server login passwords to this repository.

## 4. GitHub Release Model

The agreed release model is GitHub-first:

- `master`: development integration branch.
- `production`: production release source branch.
- feature branches: merge into `master` first.
- production promotion: open a PR from `master` or a promotion branch into
  `production`.
- production deploy: triggered from `production`.

Production code, policy, billing, runtime, provider, and deployment changes
should not be edited directly on the server. If an emergency server-side fix is
ever required, backport it to Git before the next deploy.

The production PR body should include the explicit operator approval sentence
when production validation is intended:

```text
Approved for production validation by operator.
```

Branch protection and environment approval should be enabled when the GitHub
plan and repository settings support them. During early validation, the minimum
practical gate is still:

- PR to `master`;
- CI green;
- PR to `production`;
- CI green;
- production deploy;
- public smoke checks.

## 5. Static Legal / Policy Pages

Public legal and policy pages were added under:

```text
site/terms/
```

The public links include:

- `https://cloud.npc.ink/terms`
- `https://cloud.npc.ink/terms/en/terms.html`
- `https://cloud.npc.ink/terms/en/privacy.html`
- `https://cloud.npc.ink/terms/en/data-retention.html`
- `https://cloud.npc.ink/terms/zh/terms.html`
- `https://cloud.npc.ink/terms/zh/privacy.html`
- `https://cloud.npc.ink/terms/zh/data-retention.html`

The `/terms` entrypoint was fixed so it does not expose an internal port in
redirects.

Relevant rollout PRs:

- `#37`: add static terms pages and release gates.
- `#39`: promote static terms pages to production.
- `#40`: fix `/terms` entrypoint redirect in production.
- `#41`: backport the `/terms` redirect fix to `master`.
- `#42`: add the static terms fast deploy path.
- `#43`: promote the static terms fast deploy path to production.

## 6. Static Terms Fast Deploy Path

The deployment workflow was optimized for future legal/policy page-only changes.

If a production push changes only files under:

```text
site/terms/*
```

the workflow classifies it as a static terms-only deployment. The intended fast
path is:

- skip backend CI;
- skip frontend CI;
- skip full Docker rebuild and full service redeploy;
- package and upload only `site/terms`;
- replace the production `current/site/terms` directory;
- smoke-test `/terms`, English terms, Chinese terms, CSS, and `/health/live`.

If the change touches API code, frontend app code, Docker files, proxy config,
database migrations, provider/runtime logic, CI, deployment scripts, or release
policy, it must use the full deployment path.

The first rollout of the fast path itself necessarily used the full path because
it changed workflow and deployment scripts. The production run for that rollout
completed successfully, with the deploy job taking about 6 minutes and 45
seconds and the full run taking about 12 minutes. Future `site/terms/*`-only
updates should be noticeably faster, subject to GitHub runner queue time and SSH
network speed.

The first real content-only terms update after this document should verify that
the `static-terms` job runs and that the full Docker deploy is skipped.

## 7. Why Full Cloud Deployments Are Slow

The observed full production path is slow because it does real production work:

- waits for GitHub runner scheduling;
- runs backend checks, including Python tests;
- runs frontend checks;
- builds or packages production artifacts;
- uploads release artifacts over SSH;
- starts/restarts Docker runtime services;
- runs migrations and provider/runtime refresh steps;
- runs production smoke checks.

Docker makes the runtime repeatable, but it does not remove CI, artifact upload,
remote container orchestration, migrations, or smoke verification. Docker solves
environment consistency; it does not make every deployment a static file sync.

## 8. Future Update Rules

For normal feature work:

1. Make local changes.
2. Open a PR to `master`.
3. Wait for CI.
4. Promote to `production` through a production PR.
5. Wait for production deploy.
6. Verify public endpoints.

For policy/legal static page text changes only:

1. Edit only files under `site/terms/*`.
2. Open a PR to `master`.
3. Promote to `production`.
4. Confirm the static terms fast path runs.
5. Verify the public terms URLs.

For production runtime config-only changes:

- update server-side environment configuration;
- restart only the needed service if appropriate;
- record the change in Git documentation if it changes operating assumptions.

Do not directly edit production application code or policy HTML on the server.
Server edits are easy to lose on the next deploy and bypass review history.

## 9. AI Agent Operating Notes

Future AI agents should follow these rules when continuing production work:

- start by checking `git status --short --branch`;
- read `README.md` and relevant Cloud boundary docs before editing;
- keep changes scoped to one module per session;
- do not stage unrelated dirty worktree changes;
- do not use `git add -A` in a mixed worktree;
- never write secrets into docs, tests, scripts, PR bodies, or commit messages;
- prefer GitHub as the publish source unless the operator explicitly asks for
  Gitee;
- keep Cloud within hosted runtime, provider execution, usage, entitlement,
  health, diagnostics, artifacts, and read-only runtime metadata boundaries;
- do not turn Cloud into a second WordPress control plane, ability registry,
  workflow registry, prompt/router truth, or final write owner.

## 10. Current Residual Risks

The current early-production setup is suitable for low traffic validation, but
operators should still watch:

- memory pressure on the small production server;
- database backup and restore readiness;
- production SMTP delivery and bounce/failure symptoms;
- provider health and quota errors;
- production logs after deploy;
- branch protection and environment approval availability;
- whether the next `site/terms/*`-only production update actually takes the
  fast path.

If traffic or operational importance increases, revisit server sizing, managed
database options, backup automation, observability, and stricter GitHub
environment approvals.

## 11. 2026-06-25 Admin Proxy Follow-Up

After the first production deployment, the platform-admin page reported:

```text
GET https://cloud.npc.ink/api/admin/overview 502 (Bad Gateway)
```

The production symptom was treated as a runtime/proxy issue, not as an admin UI
feature request. The validated fix was the admin proxy runtime environment
backport:

- production-facing fix PR: `#57` into `production`;
- master backport PR: `#56` into `master`;
- touched runtime contract surface:
  - `frontend/next.config.mjs`;
  - `tests/contract/test_deploy_config_contract.py`;
- post-fix live probe without an admin session returned
  `auth.admin_session_required` instead of `502`.

That `401` style response is the expected unauthenticated behavior for the
admin overview route. It confirms that the public proxy and backend chain are
reachable; it does not grant admin access.

Operational lesson: login/session or internal-token changes are runtime
configuration work unless application code changes are required. They should not
trigger a full code deployment by default. Prefer updating server-side
`.env.deploy`, restarting only the needed service, and recording the operational
assumption in Git documentation when the behavior matters.

## 12. 2026-06-25 Master CI Cleanup During Backport

While getting the `#56` backport into `master`, the branch exposed unrelated
master baseline failures. Those were handled as separate cleanup PRs:

- `#58`: fixed backend Ruff/import-order and typing baseline issues;
- `#59`: stabilized the stats alert-window test.

Both PRs merged with `classify`, `backend`, and `frontend` checks green. They
were master-quality cleanup items and were not production feature changes.

The final `#56` PR also showed `tests/api/test_stats_routes.py` in its PR file
list because of the CI cleanup path. Treat that as repository-history
cleanliness context only:

- the mixed-in file was a test file, not production runtime code;
- CI was green when `#56` merged;
- the production validation signal remains `502` becoming
  `auth.admin_session_required`;
- do not rewrite merged `master` history during early validation only to remove
  this cosmetic PR-history issue;
- if cleanup is still useful later, open a small follow-up PR to normalize the
  final stats test shape or document it.

## 13. Captured Operating Decisions

The first production rollout established these working rules for future agents
and operators:

- The current small server shape is acceptable for early validation with low
  traffic, but memory pressure and database backup/restore readiness must remain
  on the watchlist.
- Docker makes the runtime repeatable; it does not make every deployment fast.
  Full deployments still include CI, artifact upload, container orchestration,
  migrations, provider refresh, and smoke checks.
- Static legal/policy content under `site/terms/*` has a fast path. Do not use
  that fast path for API, frontend app, Docker, proxy, database, provider,
  runtime, CI, or deployment-script changes.
- Production code and policy HTML should be changed through Git, not edited
  directly on the server.
- Server-side changes are limited to runtime secrets/config and emergency
  break-glass fixes that are backported to Git before the next deploy.
- GitHub remains the publish source for this early production flow. Do not push
  or deploy to Gitee unless the operator explicitly asks.
- Branch protection and GitHub Environment approvals can stay lightweight during
  early validation. Revisit enforced approval when external usage, paid credits,
  or multi-operator deployment risk increases.
- Future AI agents should read this document together with
  `docs/cloud-production-release-policy-v1.md` and
  `deploy/PRODUCTION_GITHUB_DEPLOY.md` before changing production release
  behavior.
