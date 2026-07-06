# Release Readiness Legacy Cleanup Closeout - 2026-07-02

Status: local closeout summary.

This document summarizes the pre-release legacy cleanup pass completed while
Npcink AI Cloud still has no public user compatibility burden. It records what
was closed, which Cloud boundaries were held, and what remains outside this
cleanup scope.

## Why This Work Happened

The starting request was a systematic review of historical residue before any
public release. The project had already moved into a strong-contraction Cloud
baseline, but several leftovers still risked confusing future operators and
agents:

- stale task-pack and root-contract references;
- test ignores for files that no longer exist;
- README links and wording that still implied retired commercial or payment
  paths;
- frontend contract aggregation that could hide failing contract checks;
- admin subscription UI wording that made service-risk evidence look like a
  product control plane;
- site capacity checks that could read stale entitlement snapshots instead of
  the current plan version.

The cleanup goal was to use the no-user window to remove ambiguity now instead
of carrying compatibility workarounds into the first release.

## Boundary Held

Cloud stayed inside the hosted runtime enhancement boundary described by the
active project docs:

- hosted runtime, provider execution, usage, entitlement, health, diagnostics,
  service evidence, and read-only metadata projections are allowed;
- WordPress remains the local control plane and final write truth;
- Cloud must not become a second ability registry, workflow registry, approval
  system, prompt/router/preset truth, or WordPress write owner;
- retired task-pack APIs and task-pack product surfaces remain retired;
- content assistance remains draft, suggestion, analysis, or runtime output
  unless a local approved write path applies it.

No cleanup item reintroduced Cloud-side WordPress mutation authority, a
task-pack surface, or a second local plugin control plane.

## Closed Work

### PR #85 - Release Readiness Leftovers

Merged into `master` through merge commit `9a31850`.

Closed items:

- archived the stale root task contract into historical docs;
- removed pytest ignores that referenced nonexistent test files;
- corrected README links and stale commercial/payment wording;
- made frontend contract aggregation fail correctly when an included contract
  check fails;
- restored Portal and Service Settings contract coverage;
- restored the fake provider key needed by local contract checks.

Verification used during the PR included frontend contract checks, type checks,
lint, anti-drift checks, release-policy checks, `pnpm run check:fast`, targeted
backend pytest runs, and GitHub CI.

### PR #86 - Admin Service Risk Surface

Merged into `master` through merge commit `5d7e747`.

Closed items:

- reframed admin subscription work as a service-risk queue instead of a broad
  subscription management surface;
- simplified the plan detail view so it links to the subscriptions queue rather
  than embedding linked-subscription cards;
- aligned i18n strings and the admin operator path e2e test with the bounded
  service-risk wording.

The product boundary decision was that Cloud admin may expose service-risk
evidence for operators, but should not present itself as a second customer
control plane for local WordPress behavior.

Verification used during the PR included the targeted admin operator path e2e,
frontend type checks, lint/contract checks, and GitHub CI.

### PR #87 - Current Plan Version Site Capacity

Merged into `master` through merge commit `c5ce084`.

Closed items:

- updated site provisioning capacity checks to prefer the current plan version
  `site_limit` when available;
- kept the entitlement snapshot fallback for older or incomplete records;
- added a regression test for newly allowed sites after a plan version change;
- clarified plan editor copy around the default template.

The product impact is that a user who changes the active plan version should not
be blocked by stale entitlement snapshot capacity when adding a site.

Verification used during the PR included targeted backend pytest coverage,
Python type checking, frontend checks, and GitHub CI.

## Current Repository State

As of this closeout record:

- `origin/master` includes PR #85, PR #86, and PR #87;
- the latest merged commit on `origin/master` is `c5ce084`;
- the current cleanup branch was created from that merge point;
- no production deploy, Gitee push, or release promotion was performed by this
  closeout;
- the main local worktree still has three unrelated frontend edits from another
  session, intentionally excluded from this document commit:
  - `frontend/src/app/admin/plans/[planId]/page.tsx`
  - `frontend/src/lib/i18n.ts`
  - `frontend/tests/e2e/admin-operator-path.spec.ts`

## Residual Follow-Up

The release-readiness legacy cleanup pass is closed for the issues listed
above. Remaining work should be handled as separate, explicitly scoped changes:

- decide whether the three unrelated local frontend edits should become their
  own branch and PR;
- before a production release, follow
  `docs/cloud-production-release-policy-v1.md` and confirm `master` CI is
  green, release scope is intentional, rollback is known, and the operator
  approval phrase is present when promoting to `production`;
- for any multi-repo closeout, run the central matrix from
  `/Users/muze/gitee/npcink-toolbox` instead of copying the matrix script into
  Cloud.

## Practical Rule Going Forward

When the project is still pre-user and pre-release, remove stale historical
surfaces directly if they are not part of an active compatibility contract.
When the surface affects WordPress writes, approval, abilities, workflows,
prompts, presets, MCP, OpenClaw, or task packs, stop and route through the
corresponding boundary document before adding product behavior.
