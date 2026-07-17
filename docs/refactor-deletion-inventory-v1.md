# Npcink AI Cloud Refactor Deletion Inventory v1

## Status

Accepted target inventory with phase-tracked implementation status:

- P1 is incomplete: the canonical site contract and runtime extraction are
  implemented, while the superseded connector marker and operator-only
  `P1-E05`/`P1-E06` evidence remain open.
- P3 is complete through the bounded Media Runtime B5 closeout.
- P4 is complete through the Portal/Admin inventory and executable evidence.
- global P5 hardening and release closure is incomplete.

## Purpose

Freeze the P1 deletion and extraction obligations and track the later P3/P4
cutovers without losing their original locators. The inventory prevents the
refactor from adding a new path while leaving the old public field, validator,
runtime branch, fixture, or oversized-service ownership active beside it.

This is a target inventory and phase-status index, not standalone proof that a
replacement or exit gate passed. Original “current evidence” locators remain
baseline evidence and must be interpreted with the explicit phase status and
linked closeout records. P1 remains WordPress-first: Cloud owns hosted execution
and runtime evidence; WordPress keeps permission, review, approval, audit, and
final-write truth.

## Inventory Rules

- Stable locators are paths plus symbols or fields. Line numbers below are only
  current evidence and will drift as implementation changes.
- `NO_COMPATIBILITY_LAYER` applies to each P1 cutover. Producers, consumers,
  validators, tests, fixtures, smoke tools, and stored fields change atomically.
- `ONE_ACTIVE_CONTRACT_VERSION` applies. A transition may prepare a replacement,
  but the superseded public version must be gone before P1 exits.
- `wordpress_url` removal deletes a public and persisted field name, aliases, and
  fallbacks. It does not delete WordPress as the current platform semantics.
- The replacement site contract is `site_url` plus
  `platform_kind=wordpress`; P0-P5 accepts no other platform kind.
- WordPress task and routing-profile semantics remain explicitly WordPress-owned.
  They must not be renamed until they merely look platform-neutral.
- Extract `RuntimeService` by behavior-preserving delegation. Add characterization
  tests first, move one responsibility at a time, and keep one facade entrypoint.
- No P1 item authorizes a from-zero runtime rewrite, a second runtime, or a second
  WordPress control plane.
- No-user status removes compatibility burden, not operational care. Inventory
  production-like configuration, provider state, service evidence, and stored
  metadata before destructive work; preserve backup and rollback evidence.
- Historical material under `docs/**`, including `docs/superpowers/**`, may retain
  old terms as archive evidence. Historical migration files may retain old
  definitions; runtime code, active tests, current schema, and active migration
  targets may not.

## P1 Identity And Connector Cutover

| ID | Current evidence (path + symbol) | Action | Replacement / owner | Phase | Executable proof |
| --- | --- | --- | --- | --- | --- |
| IDN-01 | `app/api/routes/portal.py` request models and registration/addon payloads; `app/domain/commercial/identity.py::_extract_site_wordpress_url`; `app/domain/commercial/mixins/_site_mixin.py`, `_portal_mixin.py`, and `_admin_mixin.py` parameters, metadata keys, serializers, and fallback reads; `app/adapters/notifications/base.py` and `smtp.py` registration templates; `app/dev/live_site_*` reports/CLI values; active API, domain, dev, and frontend tests. Current snapshot includes `PortalCreateSitePayload.wordpress_url`, `PortalAddonConnectionPayload.wordpress_url`, `metadata_json["wordpress_url"]`, and `metadata.get("wordpress_url") or metadata.get("url")`. | change | One canonical `site_url` field and `platform_kind=wordpress`. Commercial identity/site code owns persistence; Portal owns transport; notification and dev/smoke code only consume the canonical field. No alias, fallback, dual read, or dual write. | P1 | `rg -n 'wordpress_url' app tests` returns no active match, and a current-schema assertion proves the field is gone. Historical migration definitions remain evidence. Focused Portal, commercial identity, notification, migration, dev-tool, and serialization tests pass. A pre-change metadata inventory, backup, destructive-cutover record, and restore check exist. |
| CON-01 | `app/domain/wordpress_ai_connector/contracts.py::WP_AI_CONNECTOR_CONTRACT`, `WP_AI_CONNECTOR_RESULT_CONTRACT`, and `validate_wordpress_ai_connector_runtime_contract`; `app/api/routes/runtime.py` WordPress connector detection/dispatch; `app/domain/runtime/service.py` `_is_wordpress_ai_connector_*`, `_validate_wordpress_ai_connector_contract`, provider-input builders, output normalizers, and managed policy; `tests/api/test_wordpress_ai_connector_runtime.py`, `tests/api/test_runtime_payload_bounds.py`, inline payload fixtures, and `app/dev/production_wordpress_ai_connector_smoke.py`. | delete | Replace `wp_ai_connector_runtime.v1` with one neutral runtime envelope owned by the runtime boundary and one WordPress typed operation contract owned by a WordPress operation module. Delete the old version constants, validator, old-version fixtures/assertions, and smoke payload. Retain WordPress task/profile semantics in the WordPress module. | P1 | `rg -n 'wp_ai_connector_runtime\.v1|wp_ai_connector_result\.v1|validate_wordpress_ai_connector_runtime_contract' app tests` returns no active match, and a current-schema assertion proves no active target depends on the old contract. Historical migration definitions remain evidence. New contract tests prove fail-closed validation, `suggestion_only`, site isolation, and one active version. Rewritten production smoke passes without a WordPress write. |

The identity and connector cutovers are one integration milestone. P1 must not
land `site_url` while keeping `wordpress_url`, or add the neutral envelope while
continuing to accept `wp_ai_connector_runtime.v1` through another branch.

## P1 Runtime Module Extraction

Current fact: `app/domain/runtime/service.py` is about 8,772 lines in this
inventory snapshot. Size is a trigger for responsibility extraction, not a
license to redesign behavior from documentation alone.

| ID | Current evidence (path + symbol) | Action | Replacement / owner | Phase | Executable proof |
| --- | --- | --- | --- | --- | --- |
| RUN-01 | `app/domain/runtime/service.py::RuntimeService`; validation is spread across `_validate_runtime_data_handling_contract`, `_validate_site_knowledge_contract`, `_validate_cloud_batch_runtime_contract`, media/image/audio validators, `_validate_wordpress_ai_connector_contract`, `_validate_web_search_contract`, and `_build_execution_contract`. | extract | Keep `RuntimeService` as the single facade. Move contract validation to a focused runtime contract-validation module; WordPress typed-operation validation stays in the WordPress operation module. | P1 | Capture characterization cases before moving code. `pnpm run test:contract && pnpm run test:domain` passes before and after extraction. A module-boundary test proves the facade delegates and the extracted validators fail closed with unchanged error taxonomy. |
| RUN-02 | `RuntimeService.execute`, `process_queued_runs`, `_process_single_queued_run`, `get_run`, `get_run_result`, `cancel_run`, `_build_request_fingerprint`, `_build_run_lifecycle`, callback state, retention state, and repository calls currently share the facade implementation. | extract | A run-lifecycle/idempotency module owns site-scoped replay, create/claim/transition/cancel/result/retention behavior. `run_records` remains hosted durable run truth; Redis remains wake-up/assist only. | P1 | Characterization tests cover same-key replay, changed-payload conflict, cross-site denial, queued/running/terminal transitions, cancel, callback, and expiry. `pnpm run test:domain` and focused API run tests pass with unchanged `run_id` and error semantics. |
| RUN-03 | `RuntimeService::_execute_existing_run`, `_execute_candidate_chain`, provider-call recording, `_build_wordpress_ai_connector_provider_input`, `_normalize_wordpress_ai_connector_provider_output`, and text/classification normalization helpers combine execution and result shaping. | extract | A provider-execution module owns candidate attempts, retry/fallback, and provider-call evidence. A result-normalization module owns bounded provider-output conversion; WordPress-specific normalization stays in its typed operation module. | P1 | Characterization tests pin provider order, retries, fallback, selected provider/model/instance, usage evidence, error stage, and normalized output. `pnpm run test:domain` passes and provider adapters contain no site business logic. |
| RUN-04 | `RuntimeService::enqueue_media_derivative_run`, `_execute_media_derivative_run`, `_materialize_audio_generation_output`, and `_materialize_wordpress_ai_inline_image_output` coordinate media bytes/artifacts inside the oversized facade. | extract | An artifact-coordination module owns runtime-to-artifact orchestration and delegates typed media work to media domains. P1 only extracts behavior; P3 replaces byte transport/storage. The facade remains the single runtime entry. | P1 | Add characterization tests before extraction for artifact correlation, site scope, TTL, cleanup handoff, and failure mapping. `pnpm run test:domain` passes; no second runtime entrypoint appears. P3 storage changes are not pulled into this P1 batch. |

Extraction order is fixed: characterization tests, contract validation,
idempotency/run lifecycle, provider execution/result normalization, then artifact
coordination. Each move must be independently reviewable and revertible without
restoring a compatibility shim.

## Phase Exit Proof

P1 is not complete until every command and runtime proof below has an attached
result. A green narrow test cannot substitute for the searches or real smoke.

| Proof ID | Executable gate | Required passing evidence |
| --- | --- | --- |
| P1-E01 | `rg -n 'wordpress_url' app tests` plus a current-schema migration assertion | Search output is empty: no alias, fallback, dual read, or dual write remains. The current schema lacks the field. Historical migration evidence is not deleted because of a string search; any old term there is classified as a historical definition, not an active target. Archived documentation mentions remain allowed under `docs/**`, including `docs/superpowers/**`. |
| P1-E02 | `rg -n 'wp_ai_connector_runtime\.v1|wp_ai_connector_result\.v1|validate_wordpress_ai_connector_runtime_contract' app tests` plus a current-schema migration assertion | Search output is empty. The old validator, version, fixtures, and active tests are absent, and no current-schema target depends on them. Historical migration evidence is not deleted because of a string search; any old term there is classified as a historical definition, not an active target. |
| P1-E03 | `pnpm run test:contract && pnpm run test:domain` | Neutral-envelope, WordPress typed-operation, identity, idempotency, lifecycle, provider, normalization, and facade-delegation tests pass. |
| P1-E04 | `pnpm run check:fast && pnpm run check:seam && pnpm run check:perimeter` | Repository contract, domain, API, auth, and perimeter gates pass with no Cloud control-plane drift. |
| P1-E05 | `.venv/bin/python -m app.dev.production_wordpress_ai_connector_smoke --secret-file <redacted-secret-file> --execute-title --approval-file <operator-approval-file>` | A real WordPress request reaches the one Cloud runtime, returns a reviewable title suggestion with provider/run evidence, preserves idempotency, and performs no WordPress write. The smoke payload uses only the new envelope and WordPress operation contract. |
| P1-E06 | Operator-approved pre-cutover inventory plus migration/restore rehearsal | Production-like provider configuration, secrets references, service evidence, and stored site metadata are inventoried and recoverable. Destructive cutover removes compatibility fields without blindly deleting operational evidence. |

`NO_COMPATIBILITY_LAYER` and operational preservation are compatible: remove the
obsolete contract completely, while backing up and deliberately migrating the
current production-like state that must survive the cutover.

P3 and P4 are not complete until the following executable evidence is attached.
Use focused pytest selections where implementation adds tests; do not invent a
package script merely to name a gate.

| Proof ID | Executable gate | Required passing evidence |
| --- | --- | --- |
| P3-E01 | `rg -n 'blob_data|_source_bytes_b64|_watermark_bytes_b64|b64_json|public.?download.?token|playback.?token' app tests` plus a current-schema migration assertion | Active runtime/tests no longer depend on media `blob_data`, internal/public Base64 transport, or old token routes. Historical migrations may retain old column definitions; a new destructive migration proves the current schema removed them. A provider-required transient Base64 encode is allowed only as an explicitly reviewed adapter-edge exception. |
| P3-E02 | Focused model, migration, contract, domain, API, and security pytest selections; then `pnpm run test:contract && pnpm run test:domain && pnpm run check:fast` | The `MediaArtifact` model, destructive migration/restore, streamed artifact contract, API behavior, and security boundaries pass. Test paths and exact pytest command are recorded with the implementation evidence. |
| P3-E03 | Bounded-memory streaming tests with measured peak working set | Upload, processing, and pull stream bytes without public-runtime Base64 or whole-payload amplification. |
| P3-E04 | Cross-site, expiry, and replay security tests for signed pull | A token is site-bound, expires, cannot be replayed outside its contract, and never grants a CMS write. |
| P3-E05 | TTL, purge, orphan-reconciliation, and acknowledgement tests plus cleanup metrics | One lifecycle removes expired/orphaned bytes, preserves acknowledged evidence, and exposes actionable cleanup results. |
| P3-E06 | Operator-run real WordPress media smoke | WordPress uploads, Cloud processes, WordPress pulls, then local review/import/audit completes. Provider, usage, run, expiry, purge, and acknowledgement evidence remains inspectable. |
| P4-E01 | Portal/Admin surface inventory with path, owner, truth type, and keep/delete decision | Every candidate is classified before deletion; the record proves no unaudited specific UI removal was assumed by this inventory. |
| P4-E02 | Focused Portal/Admin contract tests; then `pnpm run check:seam && pnpm run check:perimeter` | Retained operator/runtime/commercial evidence remains readable, while Cloud exposes no CMS apply, local registry, prompt/preset truth, or final approval control. |
| P4-E03 | Read-only browser smoke with screenshots for retained Portal/Admin surfaces | Run, usage, entitlement, provider, health, diagnostic, expiry, and purge evidence is readable without creating a second WordPress control plane. |

## P3 Media Runtime Cutover

Current status: MED-03 is implemented through P3-B4B3. The legacy derivative
authenticated/public-token routes and permanent audio-asset playback surface
are deleted, while audio generation and unified signed pull remain. P3-B4C1b
implements the MED-04 TTL-purge and delivery-coordination portion with a fenced
lease; P3-B4C2a adds read-only bounded inventory reconciliation and publication
fencing, while B4C2b adds persistent two-pass, fixed-root, default-off orphan
cleanup. B4C3 completes the isolated PostgreSQL 16 multi-connection,
migration-head, claim-contention, cross-container lock, and named-volume proof;
production cleanup remains default-off. B4D completed on 2026-07-16 through a
real fail-closed WordPress-to-Cloud smoke plus the focused contract gate. B4B3 removes the dead
derivative download-count columns and v1 API/UI field. Delivery observability
now comes only from `MediaArtifactDelivery`, with operation/site/UTC-date
aggregation and transfer-only semantics in summary v2.

| ID | Current evidence (path + symbol) | Action | Replacement / owner | Phase | Executable proof |
| --- | --- | --- | --- | --- | --- |
| MED-01 | `app/core/models.py::MediaDerivativeArtifact.blob_data` and `AudioAsset.blob_data`; related migrations; artifact/audio domains and routes store or transport media bytes. | delete | `MediaArtifact` stores metadata and references bytes in `ArtifactStore`; a local volume is the first storage backend. Historical migrations remain evidence. A new destructive migration moves current schema/data with backup, rollback, and restore proof. | P3 | Model and migration tests pass. Historical migration files may retain `blob_data` definitions, but current models, schema, and runtime may not use them. `rg` proves active code/tests no longer use `blob_data` for media bytes; the new destructive migration plus restore rehearsal proves the current schema is clean and production-like evidence remains recoverable. |
| MED-02 | `app/domain/runtime/service.py` fields `_source_bytes_b64` and `_watermark_bytes_b64`; `image_generation/inline_images.py` carries `b64_json` internally. | change | Runtime exchanges artifact IDs and streamed bytes. If a provider API requires Base64, encode only transiently inside that provider adapter; Base64 must not enter the public runtime contract, persistence, or logs. | P3 | `rg` finds no internal/public Base64 byte path outside an explicitly bounded provider-adapter edge. Focused contract tests and bounded-memory streaming tests pass. |
| MED-03 | P3-B4B2 removed the media-derivative public-token/authenticated routes and permanent audio-asset playback token/model/router/config exceptions. | deleted | One site-bound signed pull contract and temporary-artifact lifecycle. Audio metering, provider-call evidence, run evidence, and the audio business capability remain. | P3 | Static deletion and `0063` migration contracts pass; signed-pull tests retain cross-site denial, expiry, replay, and verified-delivery coverage. |
| MED-03B | P3-B4B3 removed `artifact_download_count`, `artifact_last_downloaded_at`, and their v1 API/UI wording. | deleted | `MediaArtifactDelivery` is the platform-neutral transfer evidence, joined to `MediaArtifact` by artifact and site for operation and site dimensions. | P3 | `0064` near-full-shape migration preservation, summary-v2 API, started-cohort bounds, exact integrity predicates, cross-site exclusion, UTC-date aggregation, bounded site breakdown, zero-rate, anomalous-state exclusion, and frontend static contracts pass. |
| MED-04 | P3-B4C1b removes the old `media_derivatives` cleanup helper and implements one `MediaArtifact` TTL purge with database claim truth, artifact-first delivery locking, revocation, delete-outside-transaction, fenced finalize, retry, and five-count cadence evidence. P3-B4C2a adds strict local-volume inventory, read-only two-direction reconciliation, publication fencing, and independent aggregate cadence evidence. P3-B4C2b adds durable complete-pass/candidate truth, fixed-root publication sessions, per-candidate exclusive conditional deletion, all-status final recheck, retry, and crash convergence. P3-B4C3 completes the isolated PostgreSQL 16 multi-connection, migration-head, deterministic claim-contention, stale-finalizer, cross-container publication-lock, and project-owned named-volume proof. P3-B4D completes the artifact-only, fail-closed real WordPress-to-Cloud smoke and focused static contract. | consolidate, implemented through C3 isolation proof and B4D real evidence; production default-off | `MediaArtifact` remains reference truth. ADR-014 age eligibility remains evidence only; ADR-015 separately requires two complete passes, ships cleanup disabled by default, and treats proof success as enablement evidence rather than production authorization. WordPress remains local write/restore/audit truth. | P3 | C1b/C2a/C2b focused migration, lifecycle, delivery/ACK, publication, inventory, concurrency-CAS, redaction, config, and cadence tests pass. The dedicated C3 isolation gate proves PostgreSQL/PG16 and named-volume behavior. The B4D gate passed on 2026-07-16 and freezes npcink-site identity, upload/job/signed-pull/ACK, exact artifact fields, local file and HTTP facts, Core audit, adoption/reference/restore, Cloud telemetry, and fixture cleanup. |

### P3-B5 Media Closeout

Status: complete on 2026-07-16. P3-B5 closed the media release-validation batch
with exact-package manifests, fresh-environment WordPress-plus-Cloud E2E,
measured performance/memory bounds, security and proxy-trust proof,
upgrade/rollback/store recovery, media-alias deletion, a clean six-repository
central matrix, and independent review. The complete evidence is attached to
[Media Runtime B5 Closeout 2026-07-16](media-runtime-b5-closeout-2026-07-16.md).
P3-B5 is not the global P5 milestone, and production cleanup remains
default-off.

## P4 Portal/Admin Cleanup

P4 begins with a surface inventory. The candidates below are rules, not a claim
that any specific page has already been audited or approved for deletion.

Current status: complete. The accepted inventory, destructive no-compatibility
cutovers, strict client migration, bounded hot-path contraction, executable
`P4-E02` gates, and screenshot-backed `P4-E03` browser smoke are recorded in
`docs/p4-portal-admin-surface-inventory-2026-07-16.md`.

The accepted path-by-path classification and owner map are recorded in
`docs/p4-portal-admin-surface-inventory-2026-07-16.md`. ADR-016 fixes the
fail-closed account-membership, Admin browser proxy, and customer credential
decisions used by the implementation.

| ID | Current evidence (path + symbol) | Action | Replacement / owner | Phase | Executable proof |
| --- | --- | --- | --- | --- | --- |
| PORT-01 | Current review candidates are `app/api/routes/portal.py`, commercial Portal/Admin mixins, and `frontend/src/app/portal`; no specific page deletion is pre-approved here. | review, then delete | Delete only duplicated implementation truth or write controls. Retain read-only run, usage, entitlement, health, diagnostic, and media-expiry/purge evidence. WordPress remains the CMS apply owner. | P4 | Complete a surface inventory, contract tests, and screenshot/browser smoke. Proof shows Cloud exposes no CMS apply control. |
| ADM-01 | Current review candidates are `app/api/routes/service.py`, `app/domain/commercial/mixins/_admin_mixin.py`, and `frontend/src/app/admin`; no specific page deletion is pre-approved here. | review, then delete | Retain operator, provider, commercial, health, and diagnostic truth. Delete only duplicated controls or truth for local abilities, workflows, prompts, presets, approval, preflight, audit, or WordPress writes. | P4 | Complete a surface inventory, contract tests, and screenshot/browser smoke. Proof shows no local registry or approval truth moved into Cloud. |

## Deferred And Retained Items

| Retain | Ownership reason |
| --- | --- |
| Identity spine: `Site`, `Principal`, `Account`, and `Membership` | Hosted identity and site scoping remain required; the identity cutover changes fields, not this spine. |
| FastAPI, PostgreSQL, Redis, workers, providers, usage, entitlement, health, and diagnostics | These are Cloud runtime, commercial-evidence, and operational responsibilities. |
| `run_records` | Hosted durable run truth remains in Cloud; Redis is wake-up/assist only. |
| Historical migrations | Preserve them as schema and operational evidence. Use a new destructive migration for current schema/data, with inventory, backup, rollback, and restore proof. |

| Defer | Rule |
| --- | --- |
| Typecho, Z-BlogPHP, and Ghost | They are not deletion targets, but P0-P5 must not add platform branches or dormant adapters for them. |
| S3 storage | It is not a deletion target. Start with a local-volume `ArtifactStore`; do not add a dormant S3 branch before proven need. |
| Audio, video, and document processors | They are not deletion targets. Do not prebuild dormant processor branches; add only after a bounded contract and demonstrated demand. |
| Universal DAG or universal content model | Neither is a deletion target or a P0-P5 deliverable. Do not create speculative abstractions or dormant model branches. |

## Non-goals

- Implementing any P1 replacement in this documentation batch.
- Keeping `wordpress_url` or `wp_ai_connector_runtime.v1` as a deprecated alias.
- Removing WordPress task/profile semantics merely to make names look generic.
- Rewriting `RuntimeService` from zero or replacing its single-entry facade.
- Changing durable run ownership, provider infrastructure, commercial truth,
  local governance, or final WordPress write ownership.
- Implementing any P3/P4 replacement in this file or pre-deciding deletion of
  a specific Portal/Admin UI before its surface audit.
- Implementing Typecho, Z-BlogPHP, Ghost, a shared multi-CMS SDK, or a universal
  CMS content model during P1.
