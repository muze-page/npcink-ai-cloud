# Admin Surface Cleanup Closeout - 2026-07-02

Status: closed on `master`.

Related PR: <https://github.com/muze-page/npcink-ai-cloud/pull/84>

Merge commit: `fe761c8`

Restore-point commit before PR merge: `5c56e34`

## Context

The admin UI had grown too many overlapping operator surfaces:

- duplicated top tabs and left navigation for customer/service areas;
- deep nested tab stacks inside runtime/provider pages;
- legacy compatibility routes that only redirected to newer admin pages;
- plan maintenance copy and development-baseline checks that belonged to an
  earlier bootstrap phase;
- AI Resources mixing provider management, runtime evidence, health snapshots,
  and matrix/debug content in one long page.

The user wanted the Cloud admin experience to move closer to the practical
layout logic of NEW API: clear left-side group navigation, compact operator
workspaces, fewer stacked tab levels, and no explanatory marketing copy inside
utility admin surfaces.

## Boundary

This cleanup stayed inside the Cloud operator/runtime detail surface.

Allowed:

- simplify `/admin/*` layout and copy;
- keep Cloud read-only runtime, provider, billing, usage, account, and
  diagnostic evidence;
- retire obsolete redirect pages and compatibility aliases;
- update tests and docs to match the contracted surface.

Not allowed:

- make Cloud a WordPress write owner;
- add a second WordPress control plane;
- add a second ability or workflow registry;
- move prompt, router, preset, MCP, OpenClaw, approval, or preflight truth into
  Cloud;
- change production server code or secrets directly.

## What Changed

The admin shell was consolidated around a simpler operator layout:

- left navigation became the primary hierarchy;
- duplicated top-level customer/service tabs were removed;
- bottom sidebar account/action controls were removed where they duplicated the
  top operator bar;
- admin Chinese i18n coverage was completed for the affected surfaces.

The runtime/provider area was narrowed:

- `/admin/ai-resources` now focuses on provider/supplier management;
- runtime parsing, runtime configuration, capability matrix, recent runtime
  evidence, and health-style evidence were moved out of the supplier page;
- Troubleshooting owns runtime evidence and diagnostics-oriented summaries;
- provider type filters keep only the useful model-provider and
  ability-provider distinction.

The customer and plan surfaces were simplified:

- customer/service top tabs that duplicated left navigation were removed;
- historical Free/development-baseline checks were removed from plan
  maintenance;
- package detail and catalog copy now describe the current plan truth instead
  of bootstrap-era history.

Legacy routes and compatibility layers were retired:

- old admin redirect pages such as hosted models, WordPress AI routing, sites,
  and portal keys were deleted;
- hosted-model-governance compatibility responses were removed;
- tests now assert the retired provider environment routes and old rendered
  pages do not remain active.

## Verification Performed

Local Cloud gates:

- `pnpm run check:release-policy`
- `pnpm run check:fast`
- `pnpm --dir frontend run type-check`
- `pnpm --dir frontend run lint`
- targeted frontend unit contracts for admin resources, layout i18n,
  troubleshooting i18n, API proxy, and portal users
- targeted API pytest coverage for service routes, retired env routes, and
  removed rendered pages
- `git diff --check`

Cross-repo gate:

- `/Users/muze/gitee/npcink-workflow-toolbox`
  `composer quality:matrix`
- `/Users/muze/gitee/npcink-workflow-toolbox`
  `composer quality:matrix:run`

Remote checks after PR #84:

- PR body contract passed after adding the required `Scope`, `Boundary`,
  `Verification`, and `Risk` sections;
- Cloud CI passed on the PR;
- CodeQL passed on the PR;
- after merge, `master` Cloud CI passed;
- after merge, `master` CodeQL passed.

Observed non-blocking warnings:

- GitHub Actions warned that some actions still target Node.js 20 while the
  runner forces Node.js 24;
- gitleaks action reported an unexpected `args` input warning.

These were not caused by the admin cleanup and did not fail the checks.

## Git And Release State

The initial direct push to `master` was correctly rejected by GitHub branch
protection because changes must go through a pull request and required checks.

The work was pushed as:

```text
codex/admin-surface-cleanup-closeout
```

PR #84 merged into `master` with merge commit:

```text
fe761c8 Merge pull request #84 from muze-page/codex/admin-surface-cleanup-closeout
```

The temporary remote branch was deleted by the PR merge and pruned locally.

The final local state after merge was:

```text
master...origin/master
```

with no uncommitted changes.

## Production Status

Production was intentionally not promoted.

Reason: the production release checklist still contains environment and
operator gates that cannot be satisfied by a local code session alone:

- production secrets and token separation;
- TLS/trusted-host and browser origin verification;
- SMTP real mailbox login;
- worker heartbeat and cadence checks;
- OTLP sink queryability;
- database backup and rollback confirmation;
- real signed addon projection reads;
- one real signed runtime request without `runtime.provider_not_configured`;
- explicit production validation approval text required by the release policy.

The safe closeout point is therefore:

- merged and green on `master`;
- not deployed;
- production promotion deferred to a separate release session.

## Next Session Entry

If continuing toward production, start a separate release-prep session from
`master` and use:

- `docs/cloud-production-release-policy-v1.md`
- `deploy/RELEASE_CHECKLIST.md`
- `deploy/OPS_PLAYBOOK.md`

Do not fold production promotion into UI cleanup. Treat it as a release
operation with its own rollback path and operator sign-off.
