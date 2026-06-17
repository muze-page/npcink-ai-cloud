# Nightly Intelligence / Morning Brief v1

Status: active planning contract

Date: 2026-06-15

## Purpose

Nightly Intelligence gives WordPress operators a morning operating surface for
content maintenance, site quality, and reviewable writing preparation. The
feature name may appear as Nightly Site Inspection in lower-level contracts,
but the product positioning should be Nightly Intelligence.

The product should be positioned as:

`nightly site inspection + morning writing preparation + content quality scoring`

In customer-facing language:

`Nightly Intelligence = off-hours site inspection and morning editorial readiness`

It must not be positioned as "nightly auto-writing" or "hands-free publishing".
The primary promise is that slow, repetitive analysis happens off-hours, while
the site owner makes decisions in the morning.

## Decision

Build this feature in phases:

1. Basic runs locally from WordPress using `WP-Cron` as the default trigger and
   a capped local dry-run/preview path first. Do not introduce Action Scheduler
   in the first implementation.
2. Pro may offload heavy analysis to Magick AI Cloud through the existing hosted
   runtime contract.
3. Agency may show multi-site read-only summaries in Cloud Portal/Admin, but
   WordPress remains the content, approval, schedule, and write owner.

Do not build a Cloud orchestration platform for this feature. Cloud may execute
bounded runtime tasks, store run evidence, meter usage, return analysis
results, and expose read-only diagnostics. Cloud must not become the scheduler
truth, workflow truth, proposal truth, or WordPress write authority.

## Product Boundary

Nightly Intelligence is for checking, analysis, scoring, and issue discovery.

Allowed analysis:

- content quality analysis;
- data completeness checks;
- SEO/AEO/GEO gap discovery;
- missing image ALT scanning;
- stale content reminders;
- site health and content opportunity Morning Briefs.

Required output shape:

- `review_items`;
- `blocked_items`;
- `retry_guidance`;
- `morning_brief`;
- `score_breakdown`;
- `core_handoff_suggestion`.

Forbidden output and behavior:

- bulk image mutation;
- bulk tag mutation;
- bulk post updates;
- automatic publishing;
- automatic SEO/meta writing;
- direct WordPress writes;
- automatic Core proposal creation, approval, or execution.

## Local Ownership

WordPress/plugin side owns:

- nightly inspection settings and enablement;
- schedule policy, including time window and frequency;
- `WP-Cron` registration and optional server cron guidance;
- future local unattended/bulk automation through `npcink-local-automation-runtime`;
- local site enumeration for posts, pages, media, comments, taxonomies, and
  internal links;
- content scoring rule definitions and score version adoption;
- Morning Brief storage and dashboard display;
- user-facing review, approval, apply, rollback, and final WordPress writes;
- Ability definitions, runtime templates, Core proposals, preflight, and audit.

The basic edition should work without Cloud:

- manual run;
- weekly or daily WP-Cron trigger;
- capped local preview/dry-run batches;
- deterministic checks first;
- read-only report output.

Recommended basic local checks:

- missing or short meta description;
- title length and stale year markers;
- missing image alt text and missing featured images;
- low word count, missing headings, or weak structure;
- old update date for freshness-sensitive content;
- missing internal links or isolated posts;
- uncategorized or over-tagged content;
- comment and UGC risk flags using deterministic rules.

## Cloud Ownership

Cloud may support Pro and Agency editions only as runtime/service enhancement:

- hosted model execution for approved analysis abilities;
- queue-backed run execution through existing runtime workers;
- callback or polling result delivery through the existing runtime contract;
- usage, cost, quota, entitlement, and provider-call evidence;
- read-only run diagnostics and operator troubleshooting;
- redacted, site-scoped Portal summaries;
- cross-site read-only Admin/Agency summaries;
- AI-assisted analysis of evidence, risks, coverage, internal-link follow-up,
  media follow-up, and source-review tasks.

Cloud must use the existing stack and seams:

- FastAPI public runtime routes;
- PostgreSQL canonical Cloud run/usage evidence;
- Redis only for queue assist and worker wake-up;
- existing runtime worker/callback worker patterns;
- existing entitlement, usage, and audit services.

Cloud must not add:

- Temporal, Celery, RabbitMQ, Kafka, NATS, Airflow, Dagster, or Kubernetes-first
  orchestration;
- a second workflow engine;
- a second scheduler truth;
- a task-pack product surface;
- a Cloud ability registry;
- a Cloud prompt/preset/router control plane;
- direct WordPress publishing or content mutation APIs.

## Edition Shape

### Basic

Basic is local-first and low risk:

- trigger: `WP-Cron`;
- executor: capped local preview/dry-run in the current phase;
- fallback: manual run button;
- scope: capped posts/pages/media per run;
- analysis: deterministic scoring;
- output: Morning Brief in WordPress admin;
- writes: none.

Server cron is a production recommendation for sites that disable automatic
WP-Cron or need reliable off-hours execution. It should call `wp-cron.php` and
must not replace local schedule ownership.

### Pro

Pro keeps local schedule truth but offloads expensive analysis:

- WordPress chooses the nightly run and batches;
- local jobs submit approved runtime requests to Cloud;
- Cloud executes `whole_run_offload` or bounded `inline` analysis;
- results return by polling or registered terminal callback;
- local stores the Morning Brief and review queue;
- local Core/Abilities handle any later apply action.

Recommended Pro analysis:

- AI content quality explanation;
- compliance and sensitive-language assessment;
- content refresh opportunity;
- FAQ suitability signal without generating final FAQ copy by default;
- internal-link candidate reasoning;
- media and alt-text opportunity;
- writing preparation metadata based on existing site evidence.

### Agency

Agency adds Cloud read-only aggregation:

- multi-site Morning Brief summary;
- site health and action-required counts;
- cost and quota pressure;
- recurring failures and callback/runtime diagnostics;
- operator detail links.

Agency must not add cross-site WordPress mutation, Cloud-side scheduled
publishing, or Cloud-owned editorial workflows.

## Runtime Contract Direction

Use named runtime abilities owned outside Cloud. Candidate names:

```text
magick-ai-toolbox/analyze-nightly-content-batch
magick-ai-toolbox/score-content-item
magick-ai-toolbox/prepare-writing-evidence
magick-ai-toolbox/check-content-compliance
magick-ai-toolbox/summarize-morning-brief
```

Cloud may validate and execute the request, but the ability contract and feature
runtime template remain on the WordPress/plugin side.

Runtime requests should use:

- `ability_family`: `automation` for the current hosted runtime contract;
- `execution_kind`: `nightly_site_inspection`;
- `execution_pattern`: `inline` for small batches, `whole_run_offload` for
  larger hosted jobs;
- `storage_mode`: default `result_only`;
- `data_classification`: at least `internal`;
- `task_backend.callback_mode`: `polling_preferred` or
  `terminal_callback_required` only when the site has a registered callback.

Public runtime `policy` must remain limited to runtime-plane allowlisted fields.
Do not pass approval policy, write policy, final write target, or WordPress
write controls to Cloud.

## Output Contract Direction

The Morning Brief result should be structured and reviewable:

```json
{
  "contract_version": "nightly_site_inspection_result.v1",
  "run_id": "local-run-id",
  "site_id": "site-id",
  "generated_at": "2026-06-15T00:00:00Z",
  "summary": {
    "scanned_posts": 126,
    "scanned_media": 38,
    "actions_total": 19,
    "risk_total": 2
  },
  "priorities": [
    {
      "object_type": "post",
      "object_id": 123,
      "score": 67,
      "severity": "warning",
      "reason_codes": ["missing_meta_description", "stale_content"],
      "explanation": "Reviewable summary only.",
      "recommended_next_action": "review_update_brief"
    }
  ],
  "writing_preparation": [
    {
      "source_object_ids": [123, 456],
      "opportunity_kind": "refresh_existing_content",
      "evidence_summary": "Existing source evidence and gaps only.",
      "forbidden_output_absent": true
    }
  ],
  "safety": {
    "direct_wordpress_write": false,
    "requires_local_review": true,
    "cloud_scheduler_truth": false
  }
}
```

Cloud-hosted results must not include direct apply instructions, final write
payloads, WordPress credentials, nonces, cookies, or approval tokens.

The Cloud Batch result also exposes a read-only Nightly Intelligence detail
surface for the operator, support, and addon display:

```json
{
  "product_surface": "nightly_intelligence",
  "product_label": "Nightly Intelligence",
  "review_items": [],
  "blocked_items": [],
  "retry_guidance": {
    "available": false,
    "retry_owner": "not_needed",
    "operator_next_action": "review_morning_brief",
    "cloud_scheduler_truth": false,
    "direct_wordpress_write": false
  },
  "core_handoff_suggestion": {
    "available": true,
    "suggestion_type": "core_review_plan_candidate",
    "proposal_created": false,
    "requires_local_review": true,
    "direct_wordpress_write": false
  },
  "nightly_intelligence_detail": {
    "artifact_type": "nightly_intelligence_detail",
    "contract_version": "nightly_intelligence_detail.v1",
    "read_surface": "run_result_detail",
    "runtime_owner": "npcink-local-automation-runtime",
    "cloud_role": "runtime_detail",
    "truth_boundary": {
      "schedule_truth": "wordpress_local",
      "approval_truth": "wordpress_local",
      "proposal_truth": "magick_ai_core",
      "final_write_truth": "wordpress_local",
      "cloud_scheduler_truth": false,
      "direct_wordpress_write": false
    }
  }
}
```

This detail object is not a Cloud control plane. It is a bounded read/detail
surface over the current run result.

### Core Review Plan Handoff

When Cloud finds reviewable issues, it may attach a Core review-plan candidate
beside the Morning Brief result:

```json
{
  "artifact_type": "nightly_site_inspection_review_plan",
  "contract_version": "nightly_site_inspection_core_review_plan.v1",
  "requires_approval": true,
  "dry_run": true,
  "commit_execution": false,
  "direct_wordpress_write": false,
  "runtime_owner": "npcink-local-automation-runtime",
  "evidence_refs": [
    {
      "action_id": "action_001",
      "post_id": "123",
      "source_type": "post",
      "score": 67,
      "severity": "warning",
      "reason_codes": ["missing_meta_description"]
    }
  ],
  "write_actions": [
    {
      "action_id": "review_nightly_site_inspection",
      "target_ability_id": "npcink-abilities-toolkit/create-draft",
      "proposal_ready": false,
      "requires_input": ["title", "content"],
      "requires_approval": true,
      "commit_execution": false,
      "input": {
        "title": "",
        "content": "",
        "status": "draft",
        "dry_run": true,
        "commit": false
      }
    }
  ]
}
```

The local handoff target is
`npcink-toolbox/build-nightly-inspection-review-plan`, submitted through Core's
existing `/proposals/from-plan` intake. This plan deliberately creates a
blocked review proposal first with `proposal_ready=false`: Cloud supplies
evidence and prioritization, while the operator supplies draft fields locally
before any final write path exists.

### Morning Brief Core Intake Package

When a user selects one or more Morning Brief review items, Cloud may expose a
bounded intake package beside the result:

```json
{
  "artifact_type": "nightly_site_inspection_core_intake_package",
  "contract_version": "nightly_site_inspection_core_intake_package.v1",
  "available": true,
  "user_action": "select_review_item_in_morning_brief",
  "selected_review_item_ids": ["action_001"],
  "handoff_owner": "wordpress_toolbox_local",
  "handoff_surface": "morning_brief_review_queue",
  "target_owner": "magick-ai-core",
  "target_route": "core:/proposals/from-plan",
  "target_plan_ability_id": "npcink-toolbox/build-nightly-inspection-review-plan",
  "target_plan_contract": "nightly_site_inspection_core_review_plan.v1",
  "proposal_created": false,
  "proposal_state_owner": "magick-ai-core",
  "approval_truth": "wordpress_local",
  "final_write_truth": "wordpress_local",
  "cloud_role": "runtime_detail",
  "cloud_scheduler_truth": false,
  "direct_wordpress_write": false,
  "receipt_expectation": {
    "expected_local_receipt": "core_proposal_id",
    "receipt_owner": "wordpress_toolbox_local",
    "cloud_receipt_storage": "not_canonical"
  }
}
```

This package is not a Core proposal and does not create one. It is the
review-item selection envelope that the local Toolbox surface can submit to
Core. The canonical receipt is the local Core proposal id stored by WordPress;
Cloud may display or correlate that receipt later, but Cloud receipt storage is
not canonical proposal truth.

## Writing Boundary

Cloud must not perform nightly article writing generation.

Forbidden Cloud outputs for this feature:

- full article drafts;
- batch article plans;
- article titles as final suggestions;
- article bodies, sections, paragraphs, or final FAQ copy;
- SEO title, excerpt, or meta-description copy as unattended nightly output;
- Cloud-produced `article_write_plan` candidates;
- direct draft creation, scheduling, publishing, or content updates.

Allowed Cloud outputs:

- source evidence;
- content gap classification;
- refresh opportunity;
- review tasks;
- internal-link follow-up;
- media follow-up;
- compliance/risk labels;
- brief preparation metadata that a local Ability can later turn into
  reviewable writing suggestions under Core governance.

If a future version needs to generate article titles, outlines, FAQ text, or SEO
copy, that generation must run through local Ability/Core review flows and must
not be a Cloud-owned nightly batch-writing product.

## Data Storage

Local should store canonical Morning Brief data for the site owner. Prefer
custom tables over high-volume `postmeta`.

Suggested local tables:

```text
wp_magick_nightly_runs
wp_magick_nightly_tasks
wp_magick_content_scores
wp_magick_content_findings
wp_magick_content_briefs
wp_magick_ai_logs
```

Cloud stores only runtime/service evidence required by hosted execution:

- `run_records`;
- usage meter events;
- provider call evidence;
- callback status;
- bounded result payload according to `storage_mode`;
- service audit events.

Cloud result retention must follow runtime `retention_ttl` and storage policy.

## Cost And Limits

Rules should run before AI.

The local scheduler should enforce:

- content hash skip;
- `last_scanned_at`;
- score version;
- daily or monthly AI budget;
- batch size;
- max objects per run;
- manual retry.

Cloud should enforce:

- provisioned active site;
- active Cloud API key;
- entitlement and quota;
- request-size limit;
- bounded concurrency;
- abuse/risk guardrails;
- storage and retention policy.

## UI Direction

WordPress admin is the primary product surface:

- Dashboard widget;
- plugin Morning Brief page;
- priority list;
- writing preparation queue;
- risk queue;
- execution history;
- cost summary;
- explicit review/apply actions.

Cloud Portal may show only read-only service detail:

- whether recent hosted analysis succeeded;
- usage/cost/quota;
- callback/runtime failures;
- multi-site summary for Agency;
- links back to WordPress for action.

Portal must not become the main editorial workspace.

## Implementation Phases

### Phase 1: Basic Local MVP

- Add local schedule settings.
- Add `WP-Cron` trigger and manual run.
- Use capped local preview/dry-run batches.
- Implement deterministic scoring.
- Store Morning Brief locally.
- Show the report in WordPress admin.
- No Cloud dependency.
- No writes.

### Phase 2: Pro Hosted Analysis

- Define local Ability/runtime templates.
- Add Cloud request signing through Cloud Addon.
- Submit small hosted analysis batches.
- Store result-only Cloud output locally.
- Add cost and quota display.
- Keep all review/apply flows local.

### Phase 3: Reviewable Fixes

- Add local proposals for meta, excerpt, alt, taxonomy, and internal links.
- Route all applies through Core approval/preflight.
- Store diff and rollback metadata locally.
- Keep Cloud output advisory.

### Phase 4: Agency Read-Only Summary

- Add Portal/Admin read-only aggregation.
- Show multi-site attention, cost, and failure summary.
- Keep action links pointed back to WordPress.

## Acceptance Checklist

- Basic works with Cloud disabled.
- Low-traffic sites have manual run and server cron guidance.
- Local WP-Cron settings and the local automation runtime own local schedule and
  batch truth.
- Cloud hosted analysis uses existing runtime APIs and workers.
- Cloud does not introduce a second scheduler or workflow engine.
- Cloud does not generate unattended article drafts, SEO copy, or final writing
  artifacts.
- All WordPress writes require local review, approval, and preflight.
- Result payloads omit secrets, cookies, nonces, credentials, and raw provider
  payloads.
- Usage and cost are visible before enabling Pro hosted analysis.
- The UI says "Morning Brief" or "Nightly Site Inspection", not "auto-write".

## Related Contracts

- [Cloud Content Generation Boundary v1](cloud-content-generation-boundary-v1.md)
- [Cloud Bulk Article Run v1](cloud-bulk-article-run-v1.md)
- [Site Monitoring Observability v1](site-monitoring-observability-v1.md)
- [Internal AI Advisor v1](internal-ai-advisor-v1.md)
