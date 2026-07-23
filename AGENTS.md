# AGENTS.md - Npcink AI Cloud

## Session Startup Protocol

Every AI development session should start with:

1. Run `git status --short --branch`.
2. Read `README.md`.
3. Read the relevant boundary docs before editing:
   - `docs/cloud-content-generation-boundary-v1.md`
   - `docs/cloud-task-pack-boundary-v1.md`
   - `docs/cloud-agent-workflow-metadata-projection-v1.md`
   - `docs/cloud-agent-feedback-quality-gate-v1.md`
4. Briefly report the focused module, relevant Cloud boundary, and intended
   verification gate before editing.

## Product Boundary

Npcink AI Cloud is the hosted runtime enhancement layer. It may own runtime
execution, provider adapters, usage and entitlement evidence, health
diagnostics, Site Knowledge runtime/detail, artifacts, and read-only runtime
metadata projections.

Cloud must not become a second WordPress control plane, second local ability
registry, second workflow registry, final approval/preflight/audit truth,
prompt/router/preset local truth, or WordPress write owner.

## AI Development Rules

- Write a compact change envelope before editing: target repositories, focused
  module, intended change, explicit non-goals, public contracts touched,
  expected files, files or areas that must not change, required gates,
  cross-repo matrix requirement, and rollback plan.
- Keep changes scoped to one module per session.
- Before staging, inspect `git status --short --branch` and `git diff --stat`.
  Stage only files changed for the current task. Do not use `git add -A` in a
  mixed worktree.
- Do not run `git reset --hard`, `git checkout -- .`, or equivalent destructive
  cleanup unless the user explicitly asks for that exact operation.
- Before committing, verify `git diff --cached --stat` and
  `git diff --cached --name-only`; after committing, verify
  `git show --name-status --stat HEAD`.
- For multi-repo milestones, run the central matrix from
  `/Users/muze/gitee/npcink-workflow-toolbox` instead of copying the script
  into Cloud:
  `composer quality:matrix` for status and `composer quality:matrix:run` before
  cross-repo closeout.

## AI Production Operation Rules

- Production source branch is `production`; development integration branch is
  `master`.
- Follow `docs/cloud-production-release-policy-v1.md` for production release
  and emergency rules.
- Do not directly edit production application code on the server.
- Server-side changes are limited to `.env.deploy` secrets/config and emergency
  break-glass fixes.
- Any emergency server fix must be backported to Git before the next deploy.
- Do not commit SMTP passwords, provider keys, database credentials, internal
  tokens, SSH keys, or `.env.deploy`.
- Before promoting to `production`, confirm:
  - `master` CI is green;
  - release scope is intentional;
  - rollback path is known;
  - `docs/cloud-production-release-policy-v1.md` is satisfied;
  - PR body includes `Approved for production validation by operator.`
- When the worktree is dirty, use a clean temporary worktree for
  release/process changes.
- Do not use `git add -A` in a mixed worktree.
- Do not push or deploy to Gitee. Current project source control is GitHub-only.
- After changing release policy, run `pnpm run check:release-policy`.

## Verification Gates

Choose verification by change risk. The default for ordinary development is
the smallest gate that directly covers the changed behavior, not
`pnpm run check:fast`.

### Tier 1: Feature-local iteration

Use this tier for documentation, copy, i18n, bounded UI behavior, and isolated
module fixes that do not change a shared contract or infrastructure seam.

- Run the focused unit, pytest, or contract cases that exercise the changed
  behavior.
- For changed Python, run `make lint-changed`.
- For changed frontend code, run TypeScript plus ESLint only on the changed
  files.
- Run one focused E2E only when the user interaction changed.
- For documentation-only changes, use `git diff --check` plus any directly
  relevant documentation or policy contract.
- Do not run `check:fast`, `check:seam`, or the complete test suite by default.

### Tier 2: Shared or high-risk seam

Escalate when the change touches a public API or error contract, authentication,
database schema or migrations, shared models/config/database access, workers,
dependencies, Docker/Compose, CI, deployment, or security boundaries.

- Run focused regression tests first.
- Add the relevant boundary gate such as `check:anti-drift`,
  `check:perimeter`, or `check:seam`.
- Let the path-aware GitHub PR workflow run the full backend lane when its
  classifier marks the change high risk.
- Run a complete local lane only when it is needed to diagnose a failure,
  GitHub CI is unavailable, or the user explicitly requests it.

### Tier 3: Integration and release

Use full gates for integration closeout, `master`/`production` promotion,
release candidates, cross-repository milestones, and production deployment.
Select the applicable commands from:

```bash
pnpm run check:fast
pnpm run check:seam
pnpm run check:perimeter
pnpm run check:anti-drift
pnpm run check:release-policy
pnpm run lint
```

Do not escalate merely because a command is named `fast`, because many tests
exist, or because any code changed. Stop after the required tier has passed.
Report exactly what passed, failed, was skipped, or was intentionally stopped;
never describe a targeted or partial run as full-suite evidence.
