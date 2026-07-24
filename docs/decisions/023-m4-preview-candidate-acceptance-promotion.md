# ADR-023: M4 Preview Candidate and Accepted Promotion

## Status

Accepted.

## Date

2026-07-24.

## Context

M4 Preview shortens the Cloud integration loop by letting the authoring Mac
package its current worktree while M4 builds and runs Docker. That speed also
creates an evidence gap: a successful preview can come from dirty or
feature-branch source that has not reached `master`. If that distinction is not
recorded, a useful M4 fix can be mistaken for a completed repository change.

Always merging first and then performing another full M4 image build would
close the evidence gap, but would make the normal feedback loop unnecessarily
slow. The existing M4 script already fingerprints image and Compose inputs and
can safely use hot source synchronization when those inputs are unchanged.

## Decision

Use one M4 runtime with two explicit evidence states:

- direct `m4:preview:sync` and `m4:preview:deploy` operations record
  `acceptance_state=candidate`;
- candidate preview may use a feature branch or dirty source and exists for fast
  behavioral feedback;
- after review and merge, an operator runs
  `m4:preview:promote -- --pr <number>` from a clean `master` worktree;
- promotion fetches `origin/master`, requires local `HEAD` to match it, and
  requires GitHub to report that the specified PR is merged into `master`;
- promotion uses the existing source-sync path by default and records
  `acceptance_state=accepted`, the PR number, source revision, clean state, and
  deployment metadata;
- when fingerprints require an image or Compose rebuild, promotion fails closed
  and directs the operator to rerun it with `--deploy`.

Promotion remains an operator-initiated local command. GitHub-hosted CI receives
no M4 SSH credential, and M4 remains a disposable runtime without a Git checkout
or source-authoring role.

GitHub rebase merge may replace feature commit SHAs. Acceptance therefore binds
the merged PR, the current `origin/master` revision, and the deployed source
revision instead of requiring the pre-merge feature SHA to remain in history.

## Boundary

This decision governs development evidence only. It does not deploy production,
change Cloudflare DNS, Access, or Tunnel configuration, add a release
orchestrator, or give M4 source-control authority. WordPress remains the local
control plane; Cloud and M4 continue to own runtime execution and runtime
diagnostics only.

## Alternatives considered

### Treat every successful feature-branch preview as complete

Rejected. It cannot prove that the validated source was committed, reviewed,
or merged into the integration branch.

### Merge before every M4 validation

Rejected. It removes the fast candidate feedback loop and encourages merging
untested integration behavior.

### Rebuild all images after every merge

Rejected. Ordinary Python and frontend changes are already covered by the
source-sync and hot-update contract. A mandatory rebuild duplicates work
without improving evidence.

### Deploy to M4 automatically from GitHub Actions

Rejected. It would place private M4 access in hosted CI and create another
deployment control surface for a single-operator development runtime.

### Maintain separate permanent candidate and accepted M4 stacks

Rejected. A second stack adds ports, volumes, state drift, and operating cost.
The recorded state transition on one disposable runtime is sufficient.

## Consequences

- candidate feedback stays fast;
- accepted status proves that the visible M4 runtime came from clean,
  up-to-date `master` after a merged PR;
- normal post-merge acceptance is a source sync rather than a rebuild;
- dependency or runtime-configuration changes still pay the necessary rebuild
  cost exactly when fingerprints demand it;
- `m4:preview:status` becomes the durable handoff evidence;
- later candidate work intentionally replaces the accepted runtime state and
  must be promoted again before it can be reported as accepted.
