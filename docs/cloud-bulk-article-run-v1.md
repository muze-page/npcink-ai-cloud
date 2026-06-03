# Cloud Bulk Article Run v1

Status: prohibited and deprecated planning contract.

Purpose: record the decision that Magick AI Cloud must not develop hosted
article writing generation, batch article drafting, SEO-copy generation, or
Cloud publishing capabilities.

## Decision

Cloud bulk article generation is not a product surface.

Cloud must not expose:

- `bulk_article_run_v1` as an active hosted writing run;
- article title generation;
- article outline generation;
- paragraph or body drafting;
- SEO title, excerpt, or meta-description writing;
- batch article draft production;
- Cloud-produced `article_write_plan` candidates;
- Cloud article artifact import into Toolbox;
- direct Cloud publishing;
- Cloud-side WordPress scheduling.

## Reason

Article writing carries legal, compliance, platform-policy, and abuse risk.
The product avoids that risk by keeping writing as local Ability recipe
orchestration under local operator review and Core governance.

## Replacement Architecture

Article drafting belongs to the local Magick AI stack:

```text
local Ability recipe
  -> local/operator-reviewed artifacts
  -> magick-ai-toolbox/build-article-write-plan
  -> Core /proposals/from-plan
  -> Core approval and commit preflight
  -> Adapter executes magick-ai/create-draft through WordPress Abilities API
```

Cloud must not generate, store, or return article body content, draft
candidates, SEO writing, or bulk writing artifacts.

## Allowed Cloud Role

Cloud may still provide non-writing service functions:

- health and diagnostics;
- entitlement and usage detail;
- service status;
- provider/runtime infrastructure for approved non-writing tasks;
- metadata-only observability and operational summaries.

Cloud status, run records, queues, and workers must not become article workflow
truth, proposal truth, approval truth, or WordPress write authorization.

## Contract Guard

This document intentionally keeps the `bulk_article_run_v1` name as a blocked
contract identifier. If a future change attempts to introduce it as an active
route, worker, portal page, or API result shape, that change must first replace
this contract with an explicitly approved boundary decision.
