# Nightly Inspection wp/npcink Trial Record - 2026-06-17

## Scope

- Source sites:
  - `wp.local`
  - `npcink.local`
- Trial targets:
  - `/Users/muze/Local Sites/wp-trial/app/public`
  - `/Users/muze/Local Sites/npcink-trial/app/public`
- Trial URLs:
  - `http://127.0.0.1:8098`
  - `http://127.0.0.1:8099`
- Original site write policy: read-only verification only
- Clone write policy: local development setup and plugin activation allowed
- Cloud endpoint: local development Cloud at `http://127.0.0.1:8010`

The original `wp.local` and `npcink.local` sites were not modified.

## Source Baseline

The source sites were checked before cloning.

| Source site | Posts | Pages | Media | Categories | Tags | Active plugins |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `wp.local` | 40 | 19 | 36 | 65 | 110 | `wordpress-importer` |
| `npcink.local` | 1967 | 1 | 5104 | 11 | 190 | `wordpress-importer` |

## Clone Setup

- Cloned WordPress files from each source Local site.
- Excluded `wp-content/uploads/` from file copy because this trial only needs database metadata, attachment IDs, filenames, and ALT metadata.
- Copied each source database into a trial database:
  - `local_wp_trial_20260617`
  - `local_npcink_trial_20260617`
- Repointed clone `siteurl` and `home`:
  - `wp.local` -> `http://127.0.0.1:8098`
  - `npcink.local` -> `http://127.0.0.1:8099`
- Activated the trial plugin stack on both clones:
  - `npcink-governance-core`
  - `npcink-abilities-toolkit`
  - `npcink-cloud-addon`
  - `npcink-toolbox`
  - `wordpress-importer`
- Copied local development Cloud Addon and Toolbox settings from `magick-ai.local`.
- Forced Nightly settings on both clones:
  - Basic local WP-Cron: disabled
  - Pro Cloud runtime: enabled
  - post limit: 12
  - media limit: 8
  - payload mode: `metadata_only`
  - retention: 1 day

## Trial Results

### `wp-trial`

- Clone URL: `http://127.0.0.1:8098/`
- Snapshot run ID: `manual-nightly-preview-20260617061802`
- Cloud run ID: `run_457f46d5111444da8f10b1f021a6a3e4`
- Submit status: `queued`
- Final status: `succeeded`
- Status history: `queued -> queued -> succeeded`
- Objects submitted: 20
  - posts: 12
  - media: 8
- Cloud request summary:
  - execution pattern: `whole_run_offload`
  - execution kind: `nightly_site_inspection`
  - storage mode: `result_only`
  - payload mode: `metadata_only`
  - retention: 86400 seconds
- Runtime privacy:
  - excerpt included: false
  - full content included: false
  - payload minimization applied: true
  - minimized items: 8
  - minimized fields: `title`
  - raw values included in minimization report: false
- Result summary:
  - result contract: `cloud_batch_runtime_result.v1`
  - merge patch contract: `nightly_site_inspection_cloud_batch_merge.v1`
  - action count: 20
  - priority queue count: 10

### `npcink-trial`

- Clone URL: `http://127.0.0.1:8099/`
- Snapshot run ID: `manual-nightly-preview-20260617061839`
- Cloud run ID: `run_5e62ab8305d54ce7a31220dd5ba6f7ea`
- Submit status: `queued`
- Final status: `succeeded`
- Status history: `queued -> queued -> succeeded`
- Objects submitted: 20
  - posts: 12
  - media: 8
- Cloud request summary:
  - execution pattern: `whole_run_offload`
  - execution kind: `nightly_site_inspection`
  - storage mode: `result_only`
  - payload mode: `metadata_only`
  - retention: 86400 seconds
- Runtime privacy:
  - excerpt included: false
  - full content included: false
  - payload minimization applied: true
  - minimized items: 8
  - minimized fields: `filename`, `title`
  - raw values included in minimization report: false
- Result summary:
  - result contract: `cloud_batch_runtime_result.v1`
  - merge patch contract: `nightly_site_inspection_cloud_batch_merge.v1`
  - action count: 20
  - priority queue count: 10

## Safety Findings

Both trials preserved the Cloud/Core boundary:

- Cloud did not perform WordPress writes.
- Cloud remained runtime/detail only.
- Scheduler truth remained local.
- Results still require local review.
- Core proposal creation was not performed during the Cloud trial.

Confirmed safety fields on both successful runs:

- `direct_wordpress_write=false`
- `cloud_scheduler_truth=false`
- `requires_local_review=true`
- `core_proposal_created=false`
- merged Morning Brief recorded `cloud_called=true`
- merged Morning Brief recorded `action_scheduler_used=false`
- merged Morning Brief recorded `custom_tables_created=false`
- schedule truth: WordPress local runtime
- final write path: `core_proposal_required`

## Payload Minimization Finding

The WordPress-side production minimization path worked on both additional real-site clones:

- `metadata_only` requests did not include excerpts or full content.
- Media attachment free-text was generalized before Cloud submission.
- The minimization report included counts and field names only, not raw values.
- The media-heavy `npcink-trial` clone validated that filename/title minimization holds under a larger source media library.

## Product Conclusion

This round confirms that the Pro Nightly Inspection Cloud batch path is usable for a bounded real-site trial:

1. Local runtime owns snapshot collection and schedule truth.
2. Cloud receives a minimized metadata-only batch and returns runtime analysis.
3. Morning Brief merge remains review-only.
4. Core handoff/proposal creation remains a later explicit approval path, not part of the Cloud batch execution.

The next useful validation is not another same-shape site trial. The next step should be testing the operator-facing review experience: how a user reads the Morning Brief, selects review items, and hands selected items to Core proposal flow without granting Cloud direct write authority.

## Priority Queue Follow-Up

An eval-lab cross-check initially flagged `priority_queue_gap` for both
additional clone trials because `action_count=20` but the Toolbox merged
Morning Brief exposed `priority_queue_count=0`. The Cloud result already
contained `morning_brief.priority_queue`; the gap was in the local Toolbox
merge layer.

After updating the Toolbox Cloud Batch result merger, both existing run results
were reread from the clone sites without submitting new Cloud runs:

| Clone | Cloud run ID | Action count | Patch priority queue | Merged priority queue | Cloud runtime priority queue |
| --- | --- | ---: | ---: | ---: | ---: |
| `wp-trial` | `run_457f46d5111444da8f10b1f021a6a3e4` | 20 | 10 | 10 | 10 |
| `npcink-trial` | `run_5e62ab8305d54ce7a31220dd5ba6f7ea` | 20 | 10 | 10 | 10 |

The reread confirmed the Cloud/Core boundary remained intact:

- `direct_wordpress_write=false`
- `cloud_scheduler_truth=false`
- `requires_local_review=true`
- `core_proposal_created=false`
