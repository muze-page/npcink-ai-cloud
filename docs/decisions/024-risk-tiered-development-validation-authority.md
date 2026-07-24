# ADR-024: Risk-Tiered Development Validation Authority

## Status

Accepted.

## Date

2026-07-24.

## Context

M4 Preview provides the real Docker, PostgreSQL, Redis, worker, frontend,
proxy, browser, and WordPress integration runtime while the authoring Mac
remains source and Git truth. Ordinary source synchronization takes seconds,
but a cold image rebuild, full M4 contract/domain suite, GitHub checks, merge,
and accepted promotion can make one complete delivery appear to be a
36-minute edit loop.

Those operations answer different questions. Repeating all of them after every
small edit does not add proportional confidence:

- a focused test answers whether the changed seam behaves correctly;
- M4 answers whether the candidate works in the development runtime;
- GitHub required checks decide whether a revision may merge;
- accepted promotion proves that clean merged `master` is the visible M4
  runtime.

The M4 source bundle also intentionally excludes `.git`. CI governance tests
that require repository history are not meaningful in that bundle, although
they remain mandatory in Git worktrees and GitHub CI.

## Decision

Adopt a risk-tiered validation model:

1. The normal inner loop is an exact local test or
   `m4:preview:test -- --focused <tests/path-or-node-id>`, followed by source
   sync and the relevant runtime, browser, worker, or WordPress observation.
2. `m4:preview:test` exposes explicit `--contract`, `--domain`, and `--full`
   scopes. The no-argument form remains the full contract/domain gate.
3. GitHub required checks are the repository merge authority. They select the
   targeted or full gate appropriate to the changed revision.
4. A full M4 gate is reserved for high-risk or M4-specific architecture,
   migration, database, worker, networking, persistence, recovery, or runtime
   evidence that GitHub cannot represent.
5. The same full contract/domain gate must not be repeated for one revision
   without a recorded distinct reason.
6. Post-merge acceptance normally consists of source promotion, status, and
   the relevant smoke. It does not automatically rerun the full M4 suite.
7. Dependency, lock, Dockerfile, Compose, proxy, and deployment-script
   fingerprints remain the sole normal reason to pay the M4 cold-build cost.
8. A contract that specifically requires Git metadata may skip when `.git` is
   absent from the M4 bundle. That exception does not apply to product or
   runtime behavior.

Target feedback budgets are:

| Activity | Normal budget |
| --- | --- |
| ordinary source sync | at most 60 seconds; investigate above two minutes |
| focused bug-fix feedback | at most five minutes |
| required PR checks plus accepted promotion | at most 15 minutes, asynchronous where possible |
| cold image rebuild and full runtime validation | 20-40 minutes, exceptional |

These are operating targets, not correctness waivers. A high-risk change pays
the evidence cost it actually requires.

## Boundary

This decision changes development validation and command selection only. It
does not weaken Cloud product boundaries, production release gates, required
GitHub checks, secret handling, loopback exposure, migration safety, or
WordPress control-plane ownership. It does not authorize production,
Cloudflare, DNS, Access, Tunnel, Compose topology, port, or data changes.

## Alternatives considered

### Run every full suite after every edit

Rejected. It turns a seconds-long source feedback loop into a serial release
rehearsal and duplicates GitHub evidence without a distinct risk claim.

### Use only focused tests and remove full integration gates

Rejected. Focused tests cannot prove shared contracts, cross-domain drift,
migrations, worker lifecycle, or complete runtime behavior.

### Treat M4 as the only test authority

Rejected. M4 intentionally lacks Git metadata, is a disposable single-operator
runtime, and must not replace reviewed repository integration truth.

### Treat GitHub CI as the only runtime authority

Rejected. Hosted CI cannot prove the M4 Docker environment, Cloudflare-protected
preview, local tunnel, native Ollama, or real WordPress integration path.

### Automatically deploy M4 from GitHub

Rejected. It would add private M4 credentials and a second deployment control
surface to hosted CI.

## Consequences

- ordinary code and bug-fix iteration receives a focused result within minutes;
- full gates remain available and become more meaningful because their reason
  is explicit;
- GitHub and M4 retain complementary authority instead of running identical
  suites by habit;
- accepted promotion stays fast for source-only changes;
- CI-only Git contracts no longer create false M4 failures;
- agents must report why any duplicate full gate was necessary.
