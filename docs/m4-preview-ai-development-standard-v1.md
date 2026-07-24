# M4 Preview AI Development Standard v1

Status: active.

## 1. Purpose and Authority

This document is the normative execution standard for AI-assisted development
when Npcink AI Cloud uses the office M4 as its Docker integration runtime.
`MUST`, `MUST NOT`, `SHOULD`, and `MAY` are requirements with their usual
normative meanings.

The documents have separate responsibilities:

- [ADR-023](decisions/023-m4-preview-candidate-acceptance-promotion.md)
  records why one runtime has candidate and accepted states.
- [M4 Preview Development Workflow](m4-preview-development-v1.md) is the
  operational runbook for hosts, ports, commands, recovery, and implementation
  details.
- This standard tells an AI agent which path to select, what evidence to
  collect, and when it may report the work complete.

When the documents appear to conflict, preserve product and security
boundaries first, then follow this standard for the development lifecycle and
the runbook for command mechanics.

## 2. Fixed Ownership Boundaries

| Surface | Owns | Must not become |
| --- | --- | --- |
| Authoring Mac | source edits, Git worktrees, commits, pull requests, operator commands | dependent on local Docker for daily work |
| GitHub `master` | reviewed development integration truth | proof that an unpromoted M4 candidate is accepted |
| M4 | disposable Docker build, runtime, migration, test, and preview evidence | source or Git truth |
| Local WordPress | abilities, workflows, approval, preflight, final writes, local settings truth | dependent on Cloud for its control-plane truth |
| Npcink AI Cloud | hosted runtime execution and bounded runtime/service evidence | a second WordPress control plane |

M4 MUST NOT become source or Git truth. Do not edit source, create commits, or
resolve merge conflicts on M4. A runtime-only failure must be reproduced or
diagnosed there, then fixed in the authoring worktree.

WordPress remains the local control plane and final write truth. M4 and Cloud
may execute and report runtime behavior, but they do not acquire approval,
publishing, ability-registry, workflow-registry, prompt, preset, or router
ownership.

## 3. Required Session Entry

Before changing this repository, an AI agent MUST:

1. run `git status --short --branch`;
2. read `README.md`, `AGENTS.md`, this standard, and the boundary documents
   relevant to the requested module;
3. fetch `origin` when the task depends on the current integration baseline;
4. preserve all existing user changes;
5. create a clean `codex/*` worktree from current `origin/master` when the
   active worktree is dirty, on another branch, or not synchronized;
6. report a compact change envelope before editing.

The change envelope MUST state:

- repository and focused module;
- intended outcome;
- explicit non-goals;
- public contracts touched;
- expected files;
- files, services, environments, and external systems that must not change;
- verification gates;
- whether a cross-repository matrix is required;
- rollback method.

An agent MUST NOT use `reset`, `stash`, checkout-based cleanup, or overwrite
user changes merely to obtain a clean worktree.

## 4. Select the Smallest Valid Lane

M4 Preview is an integration runtime, not a mandatory inner loop. Classify the
change before selecting commands.

| Lane | Typical change | Required runtime action |
| --- | --- | --- |
| Local-only | documentation; repository policy; WordPress-only PHP/UI behavior; tests that do not need the Cloud runtime | no M4 sync by default; run the narrowest local gate |
| Cloud source | ordinary `app/**`, `frontend/**`, worker, migration, or runtime integration behavior | focused local gate, then `pnpm run m4:preview:sync` |
| Build/runtime | dependency manifests or locks; Dockerfiles; Compose, proxy, base-image, or M4 deployment-script inputs | focused local gate, then `pnpm run m4:preview:deploy` |

Risk and command choice are related but not identical:

- a database migration normally travels through `sync`, but it is high risk
  and requires migration-head and persistence verification;
- a documentation-only change may alter M4 governance contracts, but it does
  not need a runtime deployment unless runtime behavior is also being tested;
- if `sync` detects a changed build/runtime fingerprint, it MUST fail closed
  and the agent must use `deploy`;
- an agent MUST NOT choose `deploy` merely as a substitute for understanding
  the changed files.

Use the full M4 gate at integration closeout or for high-risk behavior. Do not
run the approximately nine-minute full gate after every small edit when a
focused test can provide the next useful signal.

## 5. Candidate Development Loop

For Cloud changes that need the M4 runtime, use this loop:

1. reproduce or state the failing behavior and expected result;
2. edit only in the authoring worktree;
3. run the narrowest useful local test or static gate;
4. run `m4:preview:sync`, or `m4:preview:deploy` for build/runtime inputs;
5. inspect `m4:preview:status`, focused logs, and the relevant HTTP or
   WordPress behavior;
6. repeat from the authoring worktree until the behavior is correct;
7. review the diff, commit, push, and open a pull request;
8. merge only after required review and CI;
9. promote the merged revision from the stable clean operations worktree.

Direct sync and deploy operations create a candidate:

```text
acceptance_state=candidate
```

A candidate proves the packaged worktree behaved on M4. It does not prove the
change was committed, reviewed, merged, or accepted. The agent MUST use
"candidate validated" language and MUST NOT report the task as repository-
complete at this point.

Do not commit every experimental iteration. Commit once the focused behavior,
diff, and relevant gates are coherent enough for review.

## 6. Command Selection

Run M4 commands from an authoring-Mac worktree:

```bash
# Local browser and disposable WordPress connector path
pnpm run m4:preview:tunnel

# Ordinary Cloud source update
pnpm run m4:preview:sync

# Dependency, image, Compose, proxy, or deployment-script update
pnpm run m4:preview:deploy

# Read-only evidence and focused diagnosis
pnpm run m4:preview:status
pnpm run m4:preview:logs -- <service>

# Full contract + domain integration gate
pnpm run m4:preview:test

# Existing-container recovery after M4 or Docker restart
pnpm run m4:preview:recover

# Exact service lifecycle actions
pnpm run m4:preview:restart -- <service>
pnpm run m4:preview:stop
```

Use `logs` only through the checked-in redaction path. Do not replace it with a
remote command that prints protected environment files or unredacted container
configuration.

## 7. Browser and WordPress Integration

The two access paths serve different consumers:

| Consumer | URL | Reason |
| --- | --- | --- |
| Human browser preview | `https://cloud.mqzjmax.top` | Cloudflare Access protects the public preview |
| Disposable local WordPress connector | `http://127.0.0.1:18010` | foreground SSH tunnel returns the JSON API without an Access login redirect |

For local WordPress integration:

1. keep `pnpm run m4:preview:tunnel` running in a foreground terminal;
2. open the local WordPress fixture, normally `https://magick-ai.local/`;
3. configure only the disposable test connection to use
   `http://127.0.0.1:18010`;
4. validate the WordPress-to-Cloud request and the resulting local review/write
   behavior;
5. close the tunnel with `Ctrl+C` when finished.

Do not point an automated WordPress connector at
`https://cloud.mqzjmax.top`: Cloudflare Access may return an HTML login
redirect where the connector expects JSON. Do not place Cloudflare Access
service tokens in the addon, add a permanent tunnel daemon, or replace an
already verified non-disposable WordPress connection for a preview trial.

## 8. Verification by Scope

Every completion report MUST distinguish local evidence, candidate M4
evidence, Git/PR evidence, and accepted M4 evidence.

### 8.1 Local-only lane

Run the narrowest applicable contract, lint, type, or documentation gate.
Confirm links and commands referenced by the changed documentation. M4 runtime
evidence is not required unless the change claims to alter runtime behavior.

### 8.2 Cloud source lane

At minimum:

- run focused tests for the changed seam;
- run `m4:preview:sync`;
- verify the relevant API, frontend, worker, or WordPress behavior;
- inspect `m4:preview:status`;
- run `m4:preview:test` at closeout when the change affects shared runtime or
  when focused evidence is insufficient.

### 8.3 High-risk integration

For migrations, auth, networking, persistence, worker lifecycle, secrets,
exposure, or recovery behavior, also verify the applicable items:

- Alembic is at the current head;
- `/health/live` and the intended browser route return HTTP `200`;
- API, frontend, proxy, PostgreSQL, Redis, and required workers are healthy;
- restart policy is `unless-stopped`;
- published ports remain loopback-only;
- LAN and Tailscale direct access to published ports fails;
- logs contain no secrets;
- restart or recovery behavior is proved;
- failure containment touches only the named M4 Compose project.

Production validation, Cloudflare configuration, and external WordPress
acceptance require separate explicit authorization.

## 9. Git Review and Accepted Promotion

Before staging:

```bash
git status --short --branch
git diff --stat
```

Stage only the task files. Before committing, inspect:

```bash
git diff --cached --stat
git diff --cached --name-only
```

After committing, inspect:

```bash
git show --name-status --stat HEAD
```

Push the feature branch, open a focused pull request into `master`, and wait
for required CI and review. Production is not part of this workflow.

After the PR is merged, use the stable operations worktree:

```bash
cd /Users/muze/gitee/npcink-ai-cloud-m4-ops
git status --short --branch
git pull --ff-only origin master
pnpm run m4:preview:promote -- --pr <merged-pr-number>
pnpm run m4:preview:status
```

Promotion uses source sync by default. Add `--deploy` only when the command
reports changed build/runtime fingerprints:

```bash
pnpm run m4:preview:promote -- --pr <merged-pr-number> --deploy
```

The M4 work is accepted only when status shows:

```text
acceptance_state=accepted
promotion_pr=<merged-pr-number>
source_branch=master
source_dirty=false
source_revision=<current-origin-master-revision>
```

GitHub rebase merge may replace the feature commit SHA. Bind completion to the
merged PR, current `origin/master`, and deployed source revision rather than
requiring the pre-merge commit SHA to remain in history.

## 10. Failure and Recovery Rules

- If a candidate is broken, fix it in the authoring worktree or restore a
  known-good Git revision. Do not patch M4 source.
- If merged `master` is broken, use a reviewed fix or revert PR, then promote
  the corrected `master`. Do not create an untracked server hotfix.
- After M4 or Docker restart, run `m4:preview:status`, then
  `m4:preview:recover` when all expected containers exist.
- If an expected container is missing, use `m4:preview:deploy`.
- If an operation reports a stale lock, inspect its recorded owner and active
  processes before removing only the exact lock directory.
- Stop only the managed preview with `m4:preview:stop`.
- Destruction of the exact disposable Compose project and its volumes is a
  separate operator action and requires a fresh inventory.

An agent MUST NOT use broad Docker prune commands, wildcard volume deletion,
or commands that could affect unrelated M4 workloads.

## 11. Forbidden Actions

Without separate explicit authorization, an AI agent MUST NOT:

- deploy or modify production;
- modify Cloudflare DNS, Access, or Tunnel configuration;
- expose Docker, PostgreSQL, Redis, Ollama, or preview ports to LAN or
  Tailscale;
- print, commit, or copy secrets into logs, commands, documentation, or source;
- put M4 SSH credentials in GitHub-hosted CI;
- add a second permanent preview stack, deployment controller, or control
  plane;
- migrate WordPress approval, write, ability, workflow, prompt, preset, or
  router truth into Cloud;
- perform source development or Git operations on M4;
- report candidate validation as accepted completion.

## 12. Efficiency Guardrails

The workflow is useful only while it saves more local Docker cost than it adds
coordination cost.

Current measured reference values from 2026-07-24 are:

- ordinary candidate source sync: about 18.41 seconds;
- post-merge source promotion: about 23.05 seconds;
- full M4 contract + domain gate: about nine minutes.

These are observations, not service-level guarantees. Keep M4 as the normal
Cloud integration runtime while:

- ordinary edit-to-preview remains under two minutes;
- network, tunnel, and synchronization friction remains under ten minutes per
  working day;
- the full gate is reserved for closeout or high-risk changes;
- single-operator use does not create material queueing.

Reassess the setup when the thresholds are repeatedly exceeded, M4 downtime
costs more than 30-60 minutes per week, multiple developers need concurrent
isolated environments, public webhook stability becomes essential, x86_64
production parity reveals architecture-specific defects, tests routinely take
more than 15 minutes, or Docker memory pressure remains above roughly 70%.

Reassessment does not automatically mean buying a cloud server. First identify
whether the bottleneck is source transfer, tunnel use, image rebuilds, test
scope, resource limits, concurrency, or architecture parity, then choose the
smallest remedy.

## 13. Required Completion Report

The final handoff MUST include:

- changed files and intended scope;
- focused local gates and exact results;
- candidate M4 revision and behavior, when M4 was used;
- feature commit and pull request;
- merged `origin/master` revision;
- accepted M4 evidence, when runtime promotion was required;
- known limitations and any human/external acceptance still pending;
- confirmation that unrelated user work and production were not changed.

Use precise state labels:

- `local verified`;
- `candidate validated on M4`;
- `merged into master`;
- `accepted on M4`;
- `production not changed`;
- `human/external acceptance pending`.

Never collapse these into a single unqualified "done".

## 14. AI Checklist

```text
[ ] Worktree state inspected; user changes preserved
[ ] README, AGENTS, this standard, and relevant boundaries read
[ ] Change envelope reported
[ ] Change classified as local-only, Cloud source, or build/runtime
[ ] Narrowest local gate passed
[ ] M4 sync/deploy used only when the selected lane requires it
[ ] Candidate behavior and status verified
[ ] Diff reviewed; only task files staged
[ ] Focused commit pushed; PR reviewed and CI green
[ ] Merged master promoted when M4 acceptance is required
[ ] Accepted status matches clean current origin/master
[ ] Production, Cloudflare, unrelated M4 workloads, and secrets untouched
[ ] Final report separates each evidence state
```
