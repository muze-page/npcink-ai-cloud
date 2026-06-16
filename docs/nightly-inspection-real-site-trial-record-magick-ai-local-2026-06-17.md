# Nightly Inspection Real-Site Trial Record: magick-ai.local - 2026-06-17

Status: ready for one controlled inspection run; no real run submitted yet.

Purpose: record the first local controlled-trial attempt for Nightly Site
Inspection / Morning Brief on `magick-ai.local`. This record follows
`docs/nightly-inspection-real-site-operator-trial-2026-06-17.md`.

This is a local development trial record. It is not external production
evidence and does not count as a successful real-site cycle until one controlled
Cloud inspection run is submitted and reviewed.

## Trial Site

- Date: 2026-06-17
- Operator: Codex local operator
- WordPress site URL: `https://magick-ai.local`
- Cloud base URL: local Cloud development worktree evidence only
- Site ID: not confirmed from the WordPress admin HTML in this pass
- Account ID: not confirmed from the WordPress admin HTML in this pass
- Declared use case: local Nightly Inspection / Morning Brief operator trial
- Site category decision: local development site, approved for smoke only
- Cloud API key verified: not confirmed by submitting a runtime request
- Toolbox Pro Cloud Runtime visible: yes, authenticated admin HTML exposed Run
  Cloud inspection, Refresh Cloud quota, quota, and Core handoff UI signals
- Operator briefed on review-only boundary: yes

## Nightly Inspection Runs

No real Cloud inspection run was submitted in this attempt. The site is ready
for a single controlled run after operator confirmation, but runtime submission
was intentionally not triggered during environment repair because it may consume
Cloud quota and create remote-side state.

| Run date | Cloud run ID | Status | Items scanned | Reviewable | Critical | Warnings | Avg score | Operator reviewed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-17 | n/a | not-started | n/a | n/a | n/a | n/a | n/a | no |

## Morning Brief Review

- Did the priority queue identify the right first items: not evaluated
- Useful issue groups: not evaluated
- Noisy issue groups: not evaluated
- Missing context: no Cloud run output yet; local WordPress content was readable
  through WP-CLI after correcting the local DB host/socket mismatch
- Confusing labels or copy: not evaluated
- Did the brief save editorial time: not evaluated
- Did the operator need Core handoff: not evaluated
- Any attempted Cloud write or direct mutation: no

## Feedback Loop

- Feedback events submitted: no
- Accepted items: none
- Rejected items: none
- Wrong priority labels: none
- Already handled labels: none
- Evidence weak labels: none
- Wrong next step labels: none
- Top rejected reason codes: none
- Feedback summary checked in Cloud: not checked against a live WordPress run;
  Cloud Agent Feedback quality gate passed in clean worktree validation

## Boundary Review

- WordPress direct write absent: yes
- Cloud article generation absent: yes
- Bulk article generation absent: yes
- Local/Core final approval owner preserved: yes
- Secrets, cookies, nonces, or passwords absent from feedback: yes; no feedback
  event was submitted
- Any support or abuse concern: none observed; runtime submission was deferred
  pending an explicit one-run operator trigger

## Evidence

Cloud clean worktree:

- Branch/worktree: `/tmp/magick-ai-cloud-local-trial`
- Base commit: `a4153db Add nightly inspection feedback loop`
- `make lint-changed`: passed, no changed Cloud Python files
- `.venv/bin/pytest tests/api/test_cloud_batch_runtime.py tests/api/test_agent_feedback_routes.py tests/contract/test_nightly_site_inspection_contract.py`: 19 passed
- `pnpm run check:agent-feedback-quality`: passed, including 12 API/regression
  tests, targeted Python lint, Cloud admin type check, targeted Cloud admin
  lint, and read-only dashboard boundary contract

Toolbox local workspace:

- `composer smoke:nightly-inspection-cloud-ui`: passed
- `composer smoke:nightly-inspection-cloud-batch-merge`: passed
- `php -l tests/smoke-nightly-inspection-cloud-ui-contract.php`: passed
- `php -l tests/run.php`: passed
- `composer test:all`: passed, 1685 static contract checks plus Nightly
  Inspection smoke checks

Browser and WordPress site checks:

- Local.app and Local MySQL were running.
- `mysqladmin --defaults-file="/Users/muze/Library/Application Support/Local/run/NPb24Zg9g/conf/mysql/my.cnf" ping`:
  `mysqld is alive`.
- The default WP-CLI connection still failed because the CLI PHP process used
  the wrong local MySQL socket.
- WP-CLI succeeded with a temporary local-only `DB_HOST=127.0.0.1:10004`
  bootstrap file.
- WordPress `siteurl`: `https://magick-ai.local`.
- WordPress `home`: `https://magick-ai.local`.
- Published post/page count: `608`.
- Active runtime-related plugins included `npcink-governance-core`,
  `npcink-abilities-toolkit`, `npcink-ai-client-adapter`,
  `npcink-cloud-addon`, and `npcink-toolbox`.
- Authenticated admin HTML was fetched using a short-lived local operator auth
  cookie generated through WP-CLI for this smoke pass. The captured page did
  not contain the login form and did contain the WordPress admin bar for
  `codexadmin`.
- The Toolbox admin HTML exposed the Advanced / Cloud Runtime operator surface,
  including `Run Cloud inspection`, `Refresh Cloud quota`, quota, and Core
  handoff signals.

## Decision

- Go/no-go: go for one controlled local Cloud inspection run after operator
  confirmation
- Continue unchanged / adjust scoring / adjust Morning Brief copy / pause site:
  continue unchanged into one controlled runtime submission; do not tune scoring
  or Morning Brief grouping until a real run exists
- Follow-up implementation task: none for Cloud/Toolbox feature code from this
  readiness pass; the main issue was local WP-CLI DB socket configuration
- Weekly review notes: do not tune scoring, Morning Brief grouping, or feedback
  labels from this attempt because no real inspection run occurred

## Next Attempt Checklist

Before the next local trial attempt:

1. Use the Local MySQL port/socket-aware WP-CLI bootstrap when checking
   `magick-ai.local` from the terminal.
2. Confirm the Cloud addon API key is active from the authenticated admin
   surface or from a single runtime request.
3. Submit only one controlled Nightly Inspection run.
4. Record run id, Morning Brief summary, feedback events, and boundary checks.
