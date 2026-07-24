# ADR-025: Source-Only Authoring and AI M4 Checkpoint Dispatch

## Status

Accepted.

## Date

2026-07-24.

## Context

The authoring Mac is the convenient place to edit code, manage worktrees, and
operate Git. The office M4 already owns the real development containers,
PostgreSQL, Redis, workers, frontend, proxy, migrations, and protected browser
preview.

Code changes do not become visible at `https://cloud.mqzjmax.top` merely
because a file was saved or committed. The current worktree must first be
packaged and sent through the M4 preview command. Requiring the operator to
repeat "please deploy" after every authorized implementation task creates an
avoidable handoff gap.

A file-save watcher or GitHub-to-M4 callback would close that gap mechanically,
but it would transfer half-finished edits, require long-lived credentials or
background state, and risk creating a second deployment control surface.

## Decision

Adopt source-only authoring with agent-driven task-checkpoint dispatch:

- the authoring Mac owns source edits, source/static checks, Git, pull requests,
  and operator command initiation;
- M4 is the routine Cloud Docker environment for build, execution, migration,
  runtime tests, and preview;
- a user-authorized Cloud source or build/runtime task includes authorization
  for its candidate M4 preview action;
- after a coherent task checkpoint and the narrowest useful local source/static
  check, the active AI agent runs `m4:preview:sync` or
  `m4:preview:deploy` without waiting for a second deployment request;
- the agent batches related edits and dispatches again if later source changes
  would make the current candidate stale;
- documentation-only and other local-only lanes do not trigger M4;
- an unavailable or failed M4 lane is reported as incomplete runtime evidence
  and does not silently fall back to local Docker;
- candidate and accepted states continue to follow ADR-023, while validation
  scope continues to follow ADR-024.

"Automatic" in this decision means a deliberate action performed by the active
agent within the authorized task. It does not authorize per-save watchers,
background daemons, Git hooks, GitHub-hosted M4 credentials, deployment
callbacks, or another preview/control plane.

## Boundary

This decision governs the development loop only. It does not authorize
production deployment, the `production` branch, Cloudflare DNS, Access, Tunnel
configuration, public port changes, secret movement, or direct source editing
on M4. It does not move WordPress ability, workflow, approval, preflight,
prompt, preset, router, or final-write truth into Cloud.

## Alternatives considered

### Require the operator to request every candidate sync

Rejected. Once implementation and M4 preview are already in scope, a second
prompt adds no safety boundary and is easy to forget.

### Sync after every file save

Rejected. It publishes incomplete states, increases transfer/runtime churn, and
requires a persistent watcher that is harder for another session to inspect.

### Deploy M4 from GitHub Actions

Rejected. It puts private M4 access into hosted CI and creates a second
deployment authority for a single-operator development runtime.

### Use local Docker whenever M4 is unavailable

Rejected as a silent default. It breaks the agreed source/runtime ownership
model and can produce evidence from a materially different environment.
Explicit operator authorization may select a different workflow for a specific
task.

## Consequences

- authorized Cloud changes normally become visible on M4 without a follow-up
  reminder;
- source saves alone still have no deployment side effect;
- the preview receives coherent checkpoints instead of every intermediate edit;
- M4 outages remain visible rather than being hidden by a different runtime;
- future AI sessions can recover the intended behavior from `AGENTS.md`, the
  normative standard, the runbook, and contract tests;
- candidate validation still does not equal reviewed, merged, or accepted
  completion.
