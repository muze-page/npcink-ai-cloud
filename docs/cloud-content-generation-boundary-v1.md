# Cloud Content Generation Boundary v1

Status: active.

Purpose: define how Magick AI Cloud may support content generation without
becoming a content factory, a second WordPress control plane, or a high-risk
abuse surface.

## 1. Positioning

Magick AI Cloud may provide hosted model execution for content assistance, but
it must remain the runtime enhancement layer for the local Magick AI stack.

Cloud is allowed to help produce text, summaries, translations, SEO metadata,
image descriptions, and draft suggestions. Cloud must not become the place that
owns WordPress publishing decisions, content workflow truth, prompt/preset
truth, or final write authority.

The product posture is:

`compliance-controlled content workflow assistant, not cloud content factory`

## 2. Repository Ownership

Current ownership remains:

- `magick-ai-abilities`: ability definitions, schemas, callbacks, and
  permission metadata.
- `magick-ai-core`: governance, proposal review, approval, preflight, and
  audit.
- `magick-ai-adapter`: OpenClaw channel adapter that calls Core and the
  WordPress Abilities API.
- `magick-ai-cloud-addon`: thin connector for Cloud URL/API key, signing,
  runtime calls, and read-only service status.
- `magick-ai-cloud`: hosted model runtime, routing, provider execution, usage,
  entitlement, health, diagnostics, and service-plane audit evidence.

Cloud may execute a content-related runtime request only as a bounded hosted
runtime task. WordPress writes and final publication decisions must return to
the local plugin/Core path.

## 3. Allowed Content Assistance

Allowed by default when routed through the existing runtime contract and local
governance boundary:

- article outline suggestions
- paragraph drafting as an editable suggestion
- rewrite, polish, tone adjustment, and simplification
- summarization
- translation drafts
- SEO title, excerpt, meta description, tags, and category suggestions
- media alt text and caption suggestions
- WooCommerce product description drafts
- comment reply suggestions when the result is reviewed before posting
- compliance checks, sensitive-content checks, PII checks, and AI-label
  suggestions

These outputs should be treated as drafts, suggestions, or analysis results
unless a local approved write flow explicitly applies them.

## 4. Cautiously Allowed Surfaces

These are product-valid but require stronger gates:

- batch article drafts
- batch product-description drafts
- long-form article generation
- automated translation batches
- image generation for article media
- comment reply automation
- scheduled content assistance

Minimum gates:

- provisioned and active site
- signed Cloud API key
- ability/runtime contract present
- plan entitlement and per-site quota
- bounded concurrency and request-size limits
- local approval/preflight before any WordPress write
- audit trail with `site_id`, `run_id`, ability, model/provider, timestamp,
  and result storage mode
- retention policy compatible with the request's `storage_mode`

## 5. Default-Prohibited Uses

Cloud must not intentionally provide product surfaces for:

- pornographic or sexual content generation
- gambling, betting, lottery, casino, or illegal promotion content
- fraud, phishing, impersonation, or scam scripts
- fake reviews, fake testimonials, fake comments, or simulated human social
  proof
- bulk spam, doorway pages, or low-quality SEO site-farm content
- evasion of moderation, platform detection, watermarking, or content
  provenance checks
- unauthorized rewriting, scraping, laundering, or derivative use of copyrighted
  works
- regulated high-stakes advice in legal, medical, financial, or safety-critical
  domains without a separate approved product and compliance review
- direct cloud-side publishing to WordPress or other public channels

If a site, account, prompt, ability input, or usage pattern is classified into
one of these categories, the service-plane action should be deny, suspend,
revoke key, or require manual review depending on severity.

## 6. Abuse And Eligibility Rules

Cloud content generation must not be exposed as an anonymous open API.

Minimum eligibility posture:

- runtime routes accept only pre-provisioned active sites
- onboarding captures site URL, account, and declared use case
- high-risk site categories can be denied before key issuance
- Cloud API keys can be revoked or expired from the service plane
- accounts/sites can be suspended independently of local WordPress state
- bulk and automation features require a higher trust tier than single-draft
  assistance

Risk signals should include, at minimum:

- site category and domain reputation review
- repeated blocked prompt classes
- sudden high-volume generation
- high duplicate or near-duplicate output rates
- high-risk ability families
- user attempts to bypass AI labeling, moderation, or local approval

## 7. Compliance Posture

This document is a product and engineering boundary, not legal advice.

The design target is to support compliance by default:

- generated content should support visible and/or machine-readable AI labeling
  where required by the target jurisdiction
- content-generation runs should be auditable
- sensitive input should respect `data_classification` and `storage_mode`
- personal data and user-generated content should not be sent to providers
  outside the approved processing path
- logs should preserve operational evidence without storing unnecessary prompt
  or result payloads
- takedown, suspension, and key revocation must be operationally possible

Relevant current legal references for future review:

- China `Generative AI Services Interim Measures`, effective 2023-08-15.
- China `Deep Synthesis Provisions`, effective 2023-01-10.
- China `AI-Generated Synthetic Content Labeling Measures`, effective
  2025-09-01.
- China `Copyright Law`, amended 2020.
- China `Personal Information Protection Law`, effective 2021-11-01.
- FTC final rule on fake reviews and testimonials, announced 2024-08.
- Google Search policies on scaled content abuse, spam, and AI-generated
  content.
- EU AI Act transparency obligations for generated or manipulated content.

Future legal review should replace this section with counsel-approved
jurisdiction-specific language before GA.

## 8. Runtime Contract Requirements

Content-generation runtime requests must keep using the hosted runtime contract
rather than adding a separate content platform API.

Required posture:

- Cloud consumes ability/runtime contract artifacts from the WordPress/plugin
  side.
- Cloud does not invent second ability, workflow, prompt, or preset truth.
- Cloud public runtime policy ingress remains allowlisted to runtime-plane
  fields only.
- Cloud result storage follows `storage_mode`:
  - `no_store`
  - `result_only`
  - `full_store_with_ttl`
- Cloud may meter by `ability_family`, `execution_kind`, `execution_tier`, and
  `data_classification`, but entitlement/metering does not become governance
  truth.
- Any WordPress write continues through local Core approval/preflight/audit.

## 9. Product Copy Guidance

Use:

- "draft assistance"
- "content workflow assistant"
- "reviewable suggestions"
- "compliance-controlled generation"
- "hosted runtime for approved WordPress abilities"

Avoid:

- "auto-publish content factory"
- "unlimited AI article farm"
- "fake comments"
- "traffic farming"
- "bypass moderation"
- "hands-free WordPress publishing"

Marketing, admin, and portal copy should not imply that Cloud can publish or
govern WordPress content independently.

## 10. Implementation Checklist

Before shipping content-generation features:

- confirm the ability contract lives outside Cloud
- confirm local approval/preflight remains the write gate
- classify the feature as allowed, cautious, or prohibited
- define abuse rules and deny behavior
- define quota, concurrency, and request-size limits
- define result retention and audit fields
- define AI-labeling handoff fields
- define suspension and key-revocation operator path
- update tests for prohibited policy ingress and fail-closed behavior
- run Cloud boundary review before adding any new admin, portal, or public API

## 11. Non-Goals

This document does not approve:

- a Cloud content CMS
- a Cloud prompt/preset editor
- a Cloud workflow builder
- a Cloud ability registry
- a Cloud comment-growth product
- direct publishing APIs
- customer-facing legal automation workflows
- anonymous or self-serve unrestricted content generation

Any future expansion beyond this document requires a new boundary document and
explicit review.
