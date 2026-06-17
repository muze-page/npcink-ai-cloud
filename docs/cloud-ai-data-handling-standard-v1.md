# Cloud AI Data Handling Standard v1

Status: active.

Purpose: define the minimum data-handling posture for Magick AI Cloud runtime
requests that may reach hosted models, search providers, embedding providers,
image providers, or other Cloud-managed AI services.

This standard is an engineering boundary, not legal advice. Jurisdiction-specific
legal language must be reviewed separately before GA.

## 1. Positioning

Magick AI Cloud remains a runtime/service enhancement layer. It must process only
the minimum data needed for the requested runtime task, and it must not become a
second WordPress control plane, prompt/preset truth source, compliance portal, or
content CMS.

Local WordPress/Core remains responsible for:

- ability and workflow truth;
- user approval and final write decisions;
- WordPress credentials and write authority;
- deciding which local content is eligible to send through a hosted runtime
  request.

Cloud is responsible for fail-closed runtime intake, storage mode enforcement,
provider-call telemetry, bounded diagnostics, and operator evidence.

## 2. Data Classes

Runtime requests must classify data with `data_classification`.

Current classes:

- `public`: public external or non-sensitive reference data.
- `public_site_content`: public WordPress post/page content and explicitly
  allowed approved public comments.
- `public_reference_media`: public media search/reference data.
- `internal`: ordinary site/customer operational context that is not intended for
  public exposure.
- `pii`: personal data or user/customer identifiable data.
- `secret`: credentials, signing material, provider keys, WordPress passwords,
  callback secrets, tokens, private keys, or comparable security material.

`data_classification` is not a substitute for field-level contracts. Each managed
runtime ability must still define allowed input fields, forbidden fields, output
shape, and storage behavior.

## 3. Runtime Storage Modes

Runtime requests must use one of the existing storage modes:

- `no_store`: do not persist input or result payloads beyond the execution path.
- `result_only`: do not persist input payloads; persist result payloads.
- `full_store_with_ttl`: persist input/result payloads only with a positive
  `retention_ttl`.

Current enforcement:

- `pii` and `secret` requests must use `storage_mode=no_store`.
- `secret` data is excluded from hosted runtime execution. Callers must remove
  the secret, replace it with a non-sensitive reference, or keep the operation
  local.
- runtime input with obvious secret-like fields or token/private-key patterns is
  rejected before provider execution.
- runtime input with obvious personal-data indicators must explicitly use
  `data_classification=pii`; the `pii` classification then requires
  `storage_mode=no_store`.
- `full_store_with_ttl` requires a positive `retention_ttl`.
- default compatibility remains `result_only` for non-sensitive runtime data.

The generic detector is intentionally lightweight. It is a boundary backstop for
clear mistakes such as API keys, bearer tokens, private keys, email addresses,
phone numbers, or national-id-like values. It is not a complete DLP system or a
jurisdiction-specific legal classifier.

## 4. Provider Egress Rules

Before data can be sent to an upstream model/search/embedding/image provider:

- the ability contract must be present and match the Cloud-managed ability;
- the provider credential must come from Cloud deploy secrets or operator-managed
  Cloud settings, never from WordPress runtime input;
- runtime input must not include provider API keys, request headers, WordPress
  credentials, callback secrets, final-write controls, or direct publish controls;
- PII requires an explicit `pii` classification and `no_store` request posture;
- secrets must be excluded rather than forwarded to hosted providers.

Generic hosted text/vision/embedding requests rely on the caller-provided
messages or input payload. Callers must send the smallest task-specific excerpt
or reference, not full documents, full database rows, logs, credentials, or
unbounded user history.

## 5. Feature-Level Minimums

Managed runtime features must document and test their data boundary.

Current examples:

- Site Knowledge indexes bounded public WordPress content only. Comment indexing
  is opt-in and may only accept approved public comments without author email, IP
  address, user agent, payment/contact identifiers, or credentials.
- Web Search requests must be `suggestion_only`; provider keys and WordPress
  write controls are rejected from runtime input.
- Image Source requests must use Cloud-managed provider keys and must not return
  raw prompt text in filenames or result metadata where a hash is sufficient.
- Image Generation requests must reject provider keys and WordPress write
  controls; generated media import, featured image assignment, insertion, and
  publication remain local approval/write flows.
- Internal AI Advisor inputs must be aggregated or redacted read models, not raw
  production tables, raw prompts, raw provider payloads, secrets, callback
  bodies, or WordPress content.

### 5.1 Current Outbound Data Table

| Runtime feature | May send to provider | Must exclude | Default data/storage posture |
| --- | --- | --- | --- |
| Generic hosted text | Task-specific prompt excerpt, selected context, runtime parameters needed for model execution | Provider keys, WordPress credentials, callback secrets, full logs, full database rows, final-write controls | `internal` + `result_only`; use `pii` + `no_store` when personal data is present |
| Generic hosted vision | User-selected image reference or bounded visual prompt context needed for the requested operation | Private media credentials, signed admin URLs, provider keys, raw upload secrets, final-write controls | `internal` or `public_reference_media` + `result_only`; use `pii` + `no_store` when identifiable personal data is present |
| Site Knowledge | Bounded public post/page text and explicitly allowed approved public comments | Author email, IP address, user agent, payment/contact identifiers, private drafts, credentials | `public_site_content` + feature contract storage |
| Web Search | Search query, intent, bounded search context, suggestion-only posture | Provider keys, request headers, WordPress write/apply/publish controls, callback secrets | `public` + `result_only` |
| Image Source | Search/generation context, visual constraints, public reference metadata needed to source candidates | Provider keys, WordPress write controls, raw prompt text in filenames where hashes are sufficient | `public_reference_media` + `result_only` |
| Image Generation | Prompt, style/size/options needed by the managed image provider | Provider keys, WordPress import/featured-image/publish controls, callback secrets | `internal` or `public_reference_media` + `result_only`; use `pii` + `no_store` for identifiable source content |
| Cloud Batch Runtime | Item list and batch context required for bounded worker execution | Provider keys, WordPress credentials, direct write/apply controls, secrets, unrelated site content | Ability-specific classification + storage contract |
| Internal AI Advisor | Aggregated/redacted read models, counts, status labels, bounded evidence | Raw production tables, raw prompts, raw provider payloads, secrets, callback bodies, WordPress content dumps | `internal` + `result_only` or stricter feature-specific posture |

## 6. Logging, Audit, And Diagnostics

Logs and read-model summaries may retain operational evidence such as:

- `trace_id`;
- `run_id`;
- `site_id`;
- ability name/family;
- provider/model/instance identifiers;
- token counts, latency, cost, status, error codes;
- data classification and storage mode.

Logs, audit events, diagnostics, and caches must not store by default:

- raw prompts;
- raw provider request/response payloads;
- secrets;
- callback bodies;
- unnecessary customer content;
- WordPress credentials or write payloads.

When exact user text is not required for diagnostics, store hashes, counts,
status labels, bounded snippets, or redacted summaries instead.

## 7. Implementation Checklist

Before shipping any new hosted AI interaction:

- define the runtime ability contract and allowed input fields;
- define forbidden fields and fail-closed error codes;
- define `data_classification`, `storage_mode`, and retention behavior;
- define provider egress path and credential owner;
- define whether results can be stored, cached, exported, or copied;
- add tests for provider-key rejection, write-control rejection, storage behavior,
  sensitive classification behavior, and obvious secret/PII intake mistakes;
- confirm no local control-plane truth moved into Cloud;
- update this standard or the feature-specific contract if the feature needs a
  broader data path.

## 8. Current Closeout Summary

This stage is intentionally complete at the lightweight runtime-boundary layer.
The goal is to prevent obvious over-sharing without turning Cloud into a second
compliance product, data-loss-prevention system, provider governance console, or
WordPress control plane.

Implemented posture:

- Cloud has a documented minimum-data standard for hosted AI interactions.
- Runtime `resolve` and `execute` fail closed when `pii` or `secret` requests do
  not use `storage_mode=no_store`.
- `secret`-classified requests are excluded from hosted runtime execution.
- Runtime input with obvious secret-like fields or token/private-key patterns is
  rejected before provider execution.
- Runtime input with obvious personal-data indicators must use
  `data_classification=pii`, which then requires `no_store`.
- Existing ability-specific contracts remain the main place to define allowed
  fields, forbidden fields, output shape, and storage behavior.
- The outbound data table above records the current practical baseline for each
  hosted AI interaction family.

Explicitly deferred:

- full DLP or legal classification;
- provider/region-specific compliance matrices;
- customer-facing compliance dashboards;
- audit-report product surfaces;
- a Cloud-side registry, workflow engine, router/prompt control plane, or
  WordPress write owner.

Future work should be triggered by concrete new hosted AI abilities or
jurisdiction/provider requirements. In those cases, update the relevant
feature-level contract and tests first, then extend this standard only for the
newly required data path.
