# External Trial Site Knowledge Record - wp-trial - 2026-06-20

Status: local `wp-trial` Site Knowledge rehearsal complete; not an external
customer invite.

Purpose: verify that the dedicated `site_wp_trial` Cloud identity can ingest a
bounded public WordPress content subset, return evidence-backed reviewable
assistance, and preserve the Cloud boundary as runtime/detail only.

## Scope And Boundary

- WordPress target: `/Users/muze/Local Sites/wp-trial/app/public`
- Stored WordPress URL: `http://127.0.0.1:8098`
- Cloud base URL: `http://127.0.0.1:8010`
- Cloud site ID: `site_wp_trial`
- Cloud key ID: `key_wp_trial_20260619`
- WordPress source posture: read-only public `post` / `page` extraction
- Runtime write posture: `suggestion_only`
- Direct WordPress write: not used
- Direct publishing: not used
- Batch article generation: not used
- Cloud prompt/router/workflow editor: not used
- Cloud skill registry or MCP platform: not used

This record extends the previous `wp-trial` runtime rehearsal with actual
Site Knowledge content indexing and search evidence. It remains local/staging
evidence and must not be counted as a real external customer trial.

## Preflight State

The target site still used the expected independent Cloud addon identity:

- `base_url`: `http://127.0.0.1:8010`
- `site_id`: `site_wp_trial`
- `verified`: true
- Active plugin stack:
  - `npcink-governance-core`
  - `npcink-abilities-toolkit`
  - `npcink-cloud-addon`
  - `npcink-toolbox`
  - `wordpress-importer`

Cloud dev services were running behind the local proxy and
`GET /health/live` returned `service is live`.

## Source Content

The rehearsal extracted 8 published public WordPress documents through WP-CLI:

- `Hello world!`
- `Sample Page`
- `Scheduled`
- `Page Markup And Formatting`
- `Page Image Alignment`
- `Markup: HTML Tags and Formatting`
- `Markup: Image Alignment`
- `Markup: Text Alignment`

Only public `post` and `page` records were used. Drafts, private posts,
comments, users, credentials, and WordPress admin data were not sent.

## Data Guard Finding

The first sync attempt was rejected before execution:

- Error: `runtime.pii_classification_required`
- Reason: a SHA-256-style `content_hash` value in the runtime payload matched
  the generic PII detector's numeric pattern.

This was treated as a fail-closed safety result, not bypassed. The successful
rerun kept source hashes out of the runtime payload and used stable non-PII
content refs such as `wp-trial-doc-a`.

Follow-up: formalize Site Knowledge payload guidance so content identity refs
cannot accidentally look like PII or secrets.

## Site Knowledge Runtime Evidence

Sync run:

- Run ID: `run_49f826fdfea149b5b4b1a7cff170bd1b`
- Ability: `npcink-cloud/site-knowledge-sync`
- Status: succeeded
- Sync mode: rebuild
- Indexed documents: 8
- Indexed chunks: 14
- Write posture: `suggestion_only`
- Direct WordPress write: false

Search run:

- Run ID: `run_0eae360356e3469b9938f1f681177acc`
- Ability: `npcink-cloud/site-knowledge-search`
- Intent: `writing_support_plan`
- Query: `image alignment headings blockquotes WordPress sample page`
- Status: succeeded
- Result count: 5
- Evidence gate: passed
- Write posture: `suggestion_only`
- Direct WordPress write: false
- Workflow: `writer_preparation_support`
- WordPress write owner: `wordpress_local`
- Cloud output: `pre_draft_support_plan`

Status run:

- Run ID: `run_61994f26b4044f1ebeb6423557aa3d6a`
- Ability: `npcink-cloud/site-knowledge-status`
- Status: succeeded
- Index status: ready
- Indexed posts/pages: 8
- Indexed chunks: 14
- Direct WordPress write: false

Top search evidence:

- `Page Markup And Formatting` (`post_id=1134`, score `0.5847`)
- `Page Image Alignment` (`post_id=1133`, score `0.5719`)
- `Markup: HTML Tags and Formatting` (`post_id=1178`, score `0.5683`)
- `Markup: Image Alignment` (`post_id=1177`, score `0.5613`)

The search response included a `site_knowledge_suggestion_agent` handoff with:

- `handoff_owner`: `wordpress_local`
- `requires_local_approval`: true
- `direct_wordpress_write`: false
- forbidden actions including `direct_wordpress_write`, `cloud_publish`,
  `cloud_workflow_truth`, `cloud_prompt_or_preset_truth`, and article body /
  ready-to-publish generation.

## Usage And Credit Evidence

For the three successful Site Knowledge runs:

- Runs: 3
- Provider calls: 15
- Tokens in / total: 2102
- Provider: `tei`
- Model: `tei/BAAI/bge-m3`
- Credit ledger version: `ai-credit-ledger-v2`
- Credit ledger total delta: `-36`
- Credit breakdown:
  - Runs: `-3`
  - Model tokens: `-15`
  - Vector documents: `-16`
  - Vector chunks: `-2`
  - Other provider calls: `0`

## Go / No-Go

Decision: go for local `wp-trial` Site Knowledge rehearsal only.

External invite decision: hold. This is still local/staging evidence, not an
external customer trial.

Blockers cleared:

- `site_wp_trial` can ingest a bounded public WordPress content subset.
- Site Knowledge search returns source-backed writing-support evidence.
- Evidence gate passed.
- Output stayed `suggestion_only`.
- WordPress write owner stayed `wordpress_local`.
- Cloud did not publish, mutate content, or become a control plane.
- Usage and credit detail were recorded for the Site Knowledge runs.

Remaining limitations:

- The rehearsal used the local trial clone, not a real external customer site.
- The site content is mostly WordPress theme test/default content.
- The first runtime attempt exposed that SHA-256-like payload fields can trip
  generic PII detection; payload identity refs need a durable convention.
- No external browser/admin UI review was performed in this pass.

## Next Safe Action

Prepare a small real-site trial package with:

- preflight checklist
- expected Cloud addon setting change
- exact no-write guarantees
- rollback instructions
- success criteria for addon verification, Site Knowledge sync/search/status,
  usage, credits, and billing/detail evidence

Do not enable:

- direct publishing
- batch article generation
- Cloud prompt/router/workflow editing
- Cloud skill registry
- MCP platform behavior
- customer self-serve payment or checkout
