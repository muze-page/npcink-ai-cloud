# Cloud Bulk Article Run v1

Status: active planning contract.

Purpose: define how Magick AI Cloud may prepare large article runs without
becoming a content factory, WordPress publisher, approval authority, workflow
truth, prompt/preset owner, or local control plane replacement.

## Position

Cloud bulk article work is runtime preparation. The service may generate and
store bounded article artifacts for local review, including research packs,
outlines, draft candidates, discoverability suggestions, risk reports, and
`article_write_plan` candidates.

Cloud bulk article work is not publishing. Final WordPress writes remain local,
Core-governed, preflighted, audited, and executed through the WordPress
Abilities API path.

## Contract Name

The first durable contract name is:

`bulk_article_run_v1`

Cloud may expose this contract through existing hosted runtime run/result
surfaces while the dedicated public bulk route is deferred. Any future named
bulk route must remain site-authenticated, endpoint-allowlisted, quota-bounded,
and read/write separated.

## Runtime Ownership

Cloud may own:

- run creation and durable run records;
- queue-backed worker execution;
- retry and failure evidence;
- provider routing and execution;
- usage, cost, quota, and entitlement checks;
- item-level generated artifacts;
- run/result reads;
- retention and expiry;
- service-plane audit evidence.

Cloud must not own:

- WordPress credentials;
- direct WordPress writes;
- Core proposal records;
- approval, preflight, or audit truth for WordPress writes;
- Toolbox workflow truth;
- local prompt, preset, router, ability, or OpenClaw truth;
- a Cloud publishing scheduler;
- a customer-facing bulk publish console.

## Request Shape

A `bulk_article_run_v1` request should be a hosted runtime request with bounded
inputs:

- `site_id`
- `contract_version=bulk_article_run_v1`
- `idempotency_key`
- `trace_id`
- `requested_article_count`
- `language`
- `audience`
- `topic_seeds`
- `briefs`
- `source_policy`
- `risk_policy`
- `limits`
- `retention_ttl`
- `storage_mode`

The request must reject local governance or write-control fields such as:

- `approval_policy`
- `apply_policy`
- `final_write_policy`
- `final_write_target`
- `wordpress_write_policy`
- `wordpress_write_target`
- `write_control`
- `publish`
- `post_status=publish`
- `commit=true`

## Run Status

Allowed external statuses:

- `queued`
- `running`
- `ready_for_local_review`
- `partially_ready_for_local_review`
- `cancelled`
- `failed`
- `expired`

Run status is Cloud runtime evidence only. It is not a Core proposal status,
approval status, preflight result, publish result, or WordPress write
authorization.

## Result Shape

The run result should contain bounded summary data:

- `run_id`
- `contract_version`
- `site_id`
- `status`
- `requested_article_count`
- `completed_article_count`
- `failed_article_count`
- `limits`
- `cost`
- `items`

Each ready item should contain review artifacts:

- `item_id`
- `status`
- `article_goal_brief`
- `research_evidence_pack`
- `article_outline`
- `article_draft_candidate`
- `discoverability_pack`
- `article_risk_report`
- `article_write_plan`

The `article_write_plan` candidate must stay compatible with the local Toolbox
handoff shape:

- `artifact_type=article_write_plan`
- `version>=1`
- `proposal_mode=single` for P0
- `requires_approval=true`
- `dry_run=true`
- `commit_execution=false`
- one draft-only `magick-ai/create-draft` write action for local P0 import

Cloud may mark an item `ready_for_local_review`; it must not mark it
`approved`, `preflighted`, `committed`, `published`, or `executed`.

## Abuse And Eligibility Gates

Bulk article features are cautious surfaces and require stronger gates than a
single draft suggestion:

- provisioned and active site;
- active Cloud API key with `runtime:execute` and `runtime:read`;
- plan entitlement that allows bulk content preparation;
- per-site quota and requested count limits;
- bounded concurrency;
- idempotency key;
- retention limit;
- provider cost limit;
- blocked-category checks;
- service-plane ability to suspend site or revoke key.

Cloud must fail closed for bulk spam, doorway pages, low-quality SEO site-farm
patterns, fake reviews, fake testimonials, phishing, gambling, illegal
promotion, and attempts to bypass local review or AI labeling.

## Local Handoff

The safe handoff path is:

1. Cloud prepares `bulk_article_run_v1` artifacts.
2. Cloud Addon reads run/result detail.
3. Toolbox or another local operator surface selects one or a small bounded
   set of ready items.
4. The selected item is converted to the local
   `magick-ai-toolbox/build-article-write-plan` handoff.
5. Core receives the handoff through
   `POST /wp-json/magick-ai-core/v1/proposals/from-plan`.
6. Adapter executes the allowed draft write only after Core approval and
   commit preflight, through WordPress Abilities API.

## Non-Goals

This contract does not approve:

- direct Cloud publishing;
- Cloud WordPress credentials;
- Cloud-side proposal approval;
- Cloud-side Core proposal mutation;
- public anonymous content generation;
- prompt or preset editing surfaces;
- article CMS features;
- customer-facing bulk publish UI;
- a second scheduler or workflow truth.
