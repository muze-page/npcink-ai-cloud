# Nightly Inspection Real-Site Trial Record: magick-ai.local - 2026-06-17

Status: completed controlled local Cloud inspection runs.

Purpose: record the first local controlled-trial attempt for Nightly Site
Inspection / Morning Brief on `magick-ai.local`. This record follows
`docs/nightly-inspection-real-site-operator-trial-2026-06-17.md`.

This is a local development trial record. It is not external production
evidence, but it does count as the first successful local controlled real-site
cycle for the current development stage.

## Trial Site

- Date: 2026-06-17
- Operator: Codex local operator
- WordPress site URL: `https://magick-ai.local`
- Cloud base URL: local Cloud development worktree evidence only
- Site ID: not confirmed from the WordPress admin HTML in this pass
- Account ID: not confirmed from the WordPress admin HTML in this pass
- Declared use case: local Nightly Inspection / Morning Brief operator trial
- Site category decision: local development site, approved for smoke only
- Cloud API key verified: yes, Cloud entitlement and runtime submission passed
- Toolbox Pro Cloud Runtime visible: yes, authenticated admin HTML exposed Run
  Cloud inspection, Refresh Cloud quota, quota, and Core handoff UI signals
- Operator briefed on review-only boundary: yes

## Nightly Inspection Runs

Four real Cloud inspection runs were submitted in this development trial. The
first used the local WordPress / Toolbox Cloud Batch E2E path. Two follow-up
runs used the authenticated Toolbox REST route that the admin UI button calls:
`/wp-json/npcink-toolbox/v1/nightly-inspection/cloud-batch`. The final run used
a literal browser click on the Toolbox `Run Cloud inspection` button.

| Run date | Cloud run ID | Payload | Status | Items scanned | Reviewable | Critical | Warnings | Avg score | Operator reviewed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-17 | `run_a14776eeb51043b7a1e016c5300b7aa6` | metadata-only | succeeded | 5 | 5 | 3 | 2 | 62.2 | yes |
| 2026-06-17 | `run_f2a1d9b3f3f0496ca17585b77b87fa6b` | metadata-only | succeeded | 20 | 20 | 11 | 9 | 61.65 | yes |
| 2026-06-17 | `run_2475959597604fd48582c3973aa2dfac` | excerpt | succeeded | 7 | 7 | 5 | 2 | 57.29 | yes |
| 2026-06-17 | `run_15d9bdf4cae84c4687d00a4dc600d344` | metadata-only | succeeded | 20 | 20 | 11 | 9 | 61.65 | yes |

## Morning Brief Review

- Did the priority queue identify the right first items: yes for smoke; all
  runs consistently put critical page review items with score `45` at the top
- Useful issue groups: 4-5 groups returned; useful enough for the first trial
- Noisy issue groups: none flagged in this pass
- Missing context: none blocking the smoke; metadata-only and excerpt paths both
  returned mergeable Morning Brief results
- Confusing labels or copy: none flagged in this pass
- Did the brief save editorial time: likely yes, because the priority queue
  reduced scanned items into merged local priorities for review
- Did the operator need Core handoff: yes, the result preserved review-in-Core
  posture without creating a Core proposal automatically
- Any attempted Cloud write or direct mutation: no

## Feedback Loop

- Feedback events submitted: 3
- Accepted items: first priority item `action_002` on the initial E2E run and
  the larger metadata-only REST run
- Rejected items: excerpt-mode second priority item `action_004`
- Wrong priority labels: 1
- Already handled labels: none
- Evidence weak labels: 1
- Wrong next step labels: none
- Top rejected reason codes: `short_title`, `missing_meta_description`,
  `thin_content`, `missing_internal_links`, `stale_content`
- Feedback summary checked in Cloud: individual receipt accepted for eval
- Feedback receipts: `5616`, `5623`, `5624`; all returned `status=ok`,
  `accepted_for_eval=true`, and `production_mutation=false`
- Feedback labels covered: `evidence_useful`, `operator_confidence_high`,
  `wrong_priority`, `evidence_weak`, `operator_confidence_low`

## Sample Expansion Trial

Six additional authenticated Toolbox REST route runs were completed after the
initial real-site trial. These runs used the same local `magick-ai.local`
development site and compared three sample sizes across `metadata_only` and
`excerpt` payload modes. No WordPress write, Core proposal, automatic publish,
or Cloud scheduler-truth path was used.

| Sample | Cloud run ID | Payload | Limits | Items | Critical | Warnings | Avg score | Priorities | Merged priorities | Feedback receipt | Feedback outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `meta-small` | `run_7295b64dc1284a1489cd10eff4aec87f` | metadata-only | 3 posts / 2 media | 5 | 3 | 2 | 62.2 | 5 | 3 | `5662` | accepted: `evidence_useful`, `operator_confidence_high` |
| `excerpt-small` | `run_f5e7cc6be2d54dd9b3c0d5536ab9b9ee` | excerpt | 3 posts / 2 media | 5 | 3 | 2 | 62.2 | 5 | 3 | `5663` | rejected: `already_handled` |
| `meta-medium` | `run_5ec4ae88c9424bd1b371de5dd7d3c06a` | metadata-only | 6 posts / 4 media | 10 | 6 | 4 | 60.0 | 10 | 6 | `5664` | rejected: `wrong_next_step` |
| `excerpt-medium` | `run_2a1dffdb694349adb16122fc0ee7635f` | excerpt | 6 posts / 4 media | 10 | 6 | 4 | 60.0 | 10 | 6 | `5665` | accepted: `evidence_useful`, `operator_confidence_high` |
| `meta-large-repeat` | `run_967f057675e44cc3be0221e146d6933e` | metadata-only | 12 posts / 8 media | 20 | 11 | 9 | 61.65 | 10 | 15 | `5666` | rejected: `not_relevant_to_site` |
| `excerpt-large` | `run_26f7c950e95549c0a44e3078fdea841a` | excerpt | 12 posts / 8 media | 20 | 11 | 9 | 61.65 | 10 | 15 | `5667` | rejected: `duplicate_suggestion` |

Observed sample expansion findings:

- Sample size changed the result shape as expected: 5, 10, and 20 scanned items
  produced 3, 6, and 15 merged local priorities.
- `metadata_only` and `excerpt` produced identical aggregate scores and first
  priorities on this local dataset. Current evidence does not justify making
  excerpt the default payload mode.
- The first priority remained stable across all expanded samples:
  `action_002`, page `155`, `Page with comments`, score `45`, severity
  `critical`.
- Top reason codes remained stable: `short_title`,
  `missing_meta_description`, `thin_content`, `missing_internal_links`, and
  `stale_content`.
- Feedback coverage now includes useful, already handled, wrong next step, not
  relevant to site, and duplicate suggestion labels. This is enough to observe
  Cloud eval rollups, but not enough to tune scoring weights.
- The trial uncovered one integration-detail issue in the local operator
  script: the current feedback contract uses `local_outcome` and
  `feedback_labels`, not the shorter UI-facing names `outcome` and `labels`.
  The final six feedback receipts above used the current contract successfully.

## Boundary Review

- WordPress direct write absent: yes
- Cloud article generation absent: yes
- Bulk article generation absent: yes
- Local/Core final approval owner preserved: yes
- Secrets, cookies, nonces, or passwords absent from feedback: yes
- Runtime submission remained bounded: yes, metadata-only and excerpt batches
  returned no direct WordPress write, no Cloud scheduler truth, and no automatic
  Core proposal
- Any support or abuse concern: none observed in this local development pass

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
- Browser automation against the local HTTPS admin page succeeded on the final
  pass. A literal click on `Run Cloud inspection` created run
  `run_15d9bdf4cae84c4687d00a4dc600d344`, rendered `Succeeded`, showed Cloud
  run detail, rendered the Morning Brief review queue, merged 15 local
  priorities, and displayed `Writes None` for Cloud review items.
- `wp eval-file tests/smoke-nightly-inspection-cloud-e2e.php`: passed against
  `magick-ai.local`; run id
  `run_a14776eeb51043b7a1e016c5300b7aa6`.
- Cloud entitlement exposed the Nightly Site Inspection runtime feature and
  allowed Pro Nightly Inspection batch submit.
- Cloud runtime worker processed the batch to `succeeded`.
- Cloud result contract: `cloud_batch_runtime_result.v1`.
- Toolbox normalized the Morning Brief Cloud merge patch and returned a merged
  Morning Brief preview.
- Morning Brief summary: 5 items scanned, 5 reviewable, 3 critical, 2 warnings,
  average score 62.2, score version `nightly_content_quality_score.v2`.
- First priority: `action_002`, page `155`, title `Page with comments`, score
  45, severity `critical`, next action `review_update_brief`.
- Feedback receipt accepted for eval with event id `5616`; production mutation
  remained false and final write truth remained `wordpress_local`.
- Authenticated Toolbox REST route run, metadata-only: run id
  `run_f2a1d9b3f3f0496ca17585b77b87fa6b`, 20 items scanned, 20 reviewable,
  11 critical, 9 warnings, average score 61.65, 10 priority items, 5 issue
  groups, 20 patch actions, 15 merged local priorities.
- Metadata-only REST feedback receipt: event id `5623`, outcome `accepted`,
  labels `evidence_useful` and `operator_confidence_high`, production mutation
  false.
- Authenticated Toolbox REST route run, excerpt: run id
  `run_2475959597604fd48582c3973aa2dfac`, 7 items scanned, 7 reviewable,
  5 critical, 2 warnings, average score 57.29, 7 priority items, 4 issue
  groups, 7 patch actions, 5 merged local priorities.
- Excerpt REST feedback receipt: event id `5624`, outcome `rejected`, labels
  `wrong_priority`, `evidence_weak`, and `operator_confidence_low`, production
  mutation false.
- Literal browser-click Toolbox run: run id
  `run_15d9bdf4cae84c4687d00a4dc600d344`, 20 items scanned, 20 reviewable,
  11 critical, 9 warnings, average score 61.65, 15 merged local priorities,
  no Cloud write path visible in the operator UI.
- Sample expansion REST route runs: six additional runs completed successfully
  with run ids `run_7295b64dc1284a1489cd10eff4aec87f`,
  `run_f5e7cc6be2d54dd9b3c0d5536ab9b9ee`,
  `run_5ec4ae88c9424bd1b371de5dd7d3c06a`,
  `run_2a1dffdb694349adb16122fc0ee7635f`,
  `run_967f057675e44cc3be0221e146d6933e`, and
  `run_26f7c950e95549c0a44e3078fdea841a`.
- Sample expansion feedback receipts: `5662`, `5663`, `5664`, `5665`, `5666`,
  and `5667`; all returned `status=ok` and `accepted_for_eval=true`.
- Temporary local sample-expansion evidence file:
  `/tmp/nightly-sample-expansion-trial-final-20260617100125.json`.
- Cloud targeted verification after the sample expansion doc update:
  `.venv/bin/pytest tests/api/test_cloud_batch_runtime.py tests/contract/test_nightly_site_inspection_contract.py tests/api/test_agent_feedback_routes.py`:
  19 passed.
- `magick-ai-eval-lab` cross-check:
  `composer eval:task -- task=project_quality_gate project=/Users/muze/gitee/magick-ai-cloud mode=working_diff`
  wrote local generated reports under
  `/Users/muze/gitee/magick-ai-eval-lab/project-review/generated/`.
  The only review item was an existing `sk-` shaped test marker in tracked
  test/script fixtures, not this trial document or a newly introduced secret.

## Decision

- Go/no-go: go for continuing development trials
- Continue unchanged / adjust scoring / adjust Morning Brief copy / pause site:
  continue unchanged for now; the successful E2E, REST-route, browser-click, and
  sample-expansion development runs validate the runtime path, but scoring
  should not be tuned until more varied real-content samples are collected
- Follow-up implementation task: none for Cloud/Toolbox feature code from this
  pass; the main environment issue was local WP-CLI DB socket configuration
- Weekly review notes: keep `metadata_only` as the conservative default for
  Pro Nightly Intelligence, keep `excerpt` as an explicit trial mode, and use
  feedback rollups before changing score weights, Morning Brief grouping, or
  feedback labels

## Next Attempt Checklist

Before the next local trial batch:

1. Use the Local MySQL port/socket-aware WP-CLI bootstrap when checking
   `magick-ai.local` from the terminal.
2. Run additional varied-content samples on a second real site before changing
   score weights.
3. Review Cloud feedback quality rollups for `already_handled`,
   `wrong_next_step`, `not_relevant_to_site`, and `duplicate_suggestion`.
4. Keep comparing metadata-only versus excerpt quality lift across repeated
   runs, because this local sample expansion did not show an excerpt lift.
