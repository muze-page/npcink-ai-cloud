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

Default fast gate:

```bash
pnpm run check:fast
```

Additional gates by scope:

```bash
pnpm run check:seam
pnpm run check:perimeter
pnpm run check:anti-drift
pnpm run lint
```

Before finishing a code session, run the narrowest useful gate and report
exactly what passed or failed.

## M4 Preview Completion Protocol

- Direct `m4:preview:sync` and `m4:preview:deploy` operations are candidate
  previews. They prove behavior but do not prove that the source reached
  `master`.
- Do not report an M4-validated change as accepted until its pull request is
  merged into `master` and a clean, current `origin/master` worktree runs
  `pnpm run m4:preview:promote -- --pr <number>`.
- Promotion uses source sync by default. Add `--deploy` only when the command
  reports that dependency, Dockerfile, lock-file, Compose, proxy, or deployment
  script inputs require an M4 image rebuild.
- Final evidence must show `acceptance_state=accepted`, the merged PR number,
  `source_branch=master`, `source_dirty=false`, and the current
  `origin/master` revision in `m4:preview:status`.
- GitHub rebase merge may replace feature commit SHAs. Use the merged PR,
  current `origin/master`, and deployed source revision as the acceptance
  chain; do not require the pre-merge feature SHA to remain an ancestor.
- Keep M4 access operator-initiated. Do not add M4 SSH credentials to
  GitHub-hosted CI or turn preview promotion into a second deployment control
  plane.
