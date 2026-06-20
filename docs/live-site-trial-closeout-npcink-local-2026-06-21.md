# Live Site Trial Closeout: npcink.local

Date: 2026-06-21

## Summary

The `npcink.local` live-site Cloud trial is complete.

The trial proved that a real local WordPress site can connect to Magick AI
Cloud through the standalone Cloud addon, use a dedicated Cloud identity, pass
addon Save and Verify, resolve hosted runtime routing, and execute one hosted
runtime request.

The trial intentionally stopped before Site Knowledge, WordPress content
writes, metadata monitoring, or any proposal/apply flow.

## Problem Being Solved

The project needed to move Cloud from "feature implemented" to "real site
verifiable" without expanding Cloud into a second WordPress control plane.

The core question was:

- Can `npcink.local` use Cloud as a hosted runtime/detail layer on a real
  WordPress site?
- Can the addon be installed, configured, and verified through its own admin
  surface?
- Can Cloud runtime resolve and execute work with a dedicated site/key?
- Can the proof stay bounded, auditable, and free of WordPress content writes?

## Boundary

The boundary used throughout this trial was:

- WordPress remains the control plane and final write owner.
- Cloud remains runtime/detail only.
- The addon is limited to hosted runtime access settings and transport.
- Cloud does not become a second ability registry, workflow registry, router
  truth, prompt/preset control plane, or WordPress write owner.
- Public runtime does not implicitly provision sites or rotate/reissue keys.
- Site Knowledge, content writes, proposal apply, search-replace, database
  import, and monitoring all require separate later approval.

This follows the hosted runtime contract:

- `WP 是控制面，cloud 是模型运行面。`
- Public runtime policy ingress remains bounded to `allow_fallback`.
- Runtime requests consume already-provisioned active site credentials.
- Runtime execution evidence belongs to Cloud runtime; WordPress writes remain
  local and approval-gated.

## Target

- Site label: `npcink`
- URL: `http://npcink.local/`
- WordPress root: `/Users/muze/Local Sites/npcink/app/public`
- Cloud base URL used for the trial: `http://127.0.0.1:8010`
- Cloud site identity: `site_npcink_local_live`
- Cloud account identity: `acct_npcink_local_live`
- Secret file path: `.tmp/live-site-stage1/npcink-stage1/identity/cloud-api-key.secret.json`

The secret file path is recorded as evidence only. The Cloud API Key, signing
secret, and signatures must not be copied into docs, commits, or shared
summaries.

## Approval Gates Used

Three approval gates were used. Each gate required exact user approval before
execution.

### Stage 1

Scope:

- install and activate Cloud addon on `npcink.local`;
- provision a dedicated Cloud identity;
- save Cloud Base URL and Cloud API Key through the addon backend;
- verify the addon;
- do not run runtime smoke, Site Knowledge, content writes, or monitoring.

Result: completed.

### Runtime Resolve Smoke

Scope:

- run one signed `/v1/runtime/resolve` request;
- do not run `/v1/runtime/execute`;
- do not run Site Knowledge;
- do not write WordPress content;
- do not enable monitoring.

Result: completed.

### Runtime Execute Smoke

Scope:

- run one signed `/v1/runtime/execute` request;
- do not run Site Knowledge;
- do not write WordPress content;
- do not enable monitoring.

Result: completed.

## Implementation History

The trial was built as a guarded chain of read-only gates, approval files, and
execute helpers. The goal was to make each step auditable and hard to run
accidentally.

Key supporting commits:

- `8329430` `tools: add live site stage1 readiness gate`
- `f83a4a6` `tools: load live site internal token from env files`
- `b8b7f88` `tools: support approval files for live site guards`
- `afcf835` `tools: require readiness before live site stage1 execute`
- `0118dbe` `tools: add save and verify handoff report`
- `4a826cf` `tools: include save verify handoff in trial status`
- `58cec5d` `tools: add live site stage1 execute packet`
- `b29d28b` `tools: detect current cloud addon settings option`
- `befc24e` `tools: clarify runtime resolve prepare next step`
- `4f88b4c` `tools: add runtime resolve execute packet`
- `fdf795e` `tools: add runtime execute packet`

The extra execute-packet tools were added because generic agreement is not
authorization for runtime calls. They force the chain to prove that the previous
phase is complete and that the next action exactly matches the expected phase.

## Final Evidence

Final trial status:

- report: `.tmp/live-site-trial-status/npcink-after-execute/trial-status-report.json`
- `complete=true`
- next action: `trial_chain_complete_prepare_site_knowledge_decision`

All five phases passed:

| Phase | Mode | Result | Evidence |
| --- | --- | --- | --- |
| Stage 1 addon install + Cloud identity | `execute` | `ok=true` | `.tmp/live-site-stage1/npcink-stage1/stage1-report.json` |
| Stage 1 Save and Verify handoff | `read_only_handoff` | `ok=true` | `.tmp/live-site-save-verify-handoff/npcink-stage1/save-verify-handoff-report.json` |
| Stage 1 wp-admin Save and Verify acceptance | `read_only_acceptance` | `ok=true` | `.tmp/live-site-stage1-acceptance/npcink-stage1/acceptance-report.json` |
| Runtime resolve smoke | `execute` | `ok=true` | `.tmp/live-site-runtime-smoke/npcink-resolve/runtime-resolve-smoke-report.json` |
| Runtime execute smoke | `execute` | `ok=true` | `.tmp/live-site-runtime-execute-smoke/npcink-execute/runtime-execute-smoke-report.json` |

## Stage 1 Result

Report:

- `.tmp/live-site-stage1/npcink-stage1/stage1-report.json`

Result:

- `ok=true`
- addon install/activation completed;
- dedicated Cloud identity provisioned;
- identity owner remained `internal_service_operations`;
- public runtime did not implicitly provision anything;
- runtime smoke was not run during Stage 1;
- Site Knowledge was not run;
- content writes did not happen;
- monitoring stayed disabled.

Stage 1 boundary:

- `wordpress_writes=true`, limited to plugin install/activate;
- `wordpress_option_writes=false`;
- `cloud_identity_provisioning=true`;
- `cloud_runtime_execution=false`;
- `runtime_smoke=false`;
- `site_knowledge_sync=false`;
- `site_knowledge_search=false`;
- `content_writes=false`;
- `monitoring_enabled=false`.

## Addon Verification

Stage 1 acceptance report:

- `.tmp/live-site-stage1-acceptance/npcink-stage1/acceptance-report.json`

Result:

- `ready_for_runtime_smoke_approval=true`
- failed checks: none
- addon active and verified;
- Cloud settings matched the Stage 1 identity;
- monitoring remained disabled.

The active settings option detected after the actual addon install was:

- `magick_ai_cloud_addon_settings`

This replaced the older expected `npcink_cloud_addon_settings` path in tooling.

## Runtime Resolve Smoke

Report:

- `.tmp/live-site-runtime-smoke/npcink-resolve/runtime-resolve-smoke-report.json`

Request:

- method: `POST`
- path: `/v1/runtime/resolve`
- site id: `site_npcink_local_live`
- ability: `magick-ai/workflows/generate-post-draft`
- execution pattern: `inline`
- storage mode: `result_only`
- policy: `{"allow_fallback": true}`

Result:

- `ok=true`
- HTTP status: `200`
- response status: `ok`
- response failures: none

Boundary:

- `runtime_resolve_smoke=true`
- `runtime_execute=false`
- `provider_execution=false`
- `site_knowledge_sync=false`
- `site_knowledge_search=false`
- `wordpress_writes=false`
- `content_writes=false`
- `monitoring_enabled=false`

## Runtime Execute Smoke

Report:

- `.tmp/live-site-runtime-execute-smoke/npcink-execute/runtime-execute-smoke-report.json`

Request:

- method: `POST`
- path: `/v1/runtime/execute`
- site id: `site_npcink_local_live`
- ability: `magick-ai/workflows/generate-post-draft`
- execution pattern: `inline`
- storage mode: `result_only`
- policy: `{"allow_fallback": true}`

Result:

- `ok=true`
- HTTP status: `200`
- response status: `ok`
- run status: `succeeded`
- provider id: `openai`
- model id: `ByteDance-Seed/Seed-OSS-36B-Instruct`
- provider call count: `1`
- response failures: none

Boundary:

- `runtime_execute_smoke=true`
- `provider_execution_possible=true`
- `site_knowledge_sync=false`
- `site_knowledge_search=false`
- `wordpress_option_writes=false`
- `wordpress_writes=false`
- `content_writes=false`
- `monitoring_enabled=false`

## What Was Not Done

The trial intentionally did not:

- run Site Knowledge sync;
- run Site Knowledge search;
- write WordPress posts, pages, metadata, media, terms, or options outside the
  approved addon setup path;
- apply proposals;
- enable metadata monitoring;
- run database import;
- run search-replace;
- operate on `wp.local` or `dbd.local`;
- add a Cloud control plane, registry, marketplace, router truth, or workflow
  engine.

## Sensitive Data Handling

The reports were checked for obvious secret leakage.

Allowed in reports/docs:

- secret file path;
- `site_id`;
- `key_id` presence;
- provider/model identifiers;
- runtime status;
- redacted settings.

Not allowed in reports/docs:

- customer-facing Cloud API Key;
- signing secret;
- HMAC signature;
- raw authorization headers.

The final reported secret references were limited to paths such as:

- `.tmp/live-site-stage1/npcink-stage1/identity/cloud-api-key.secret.json`

## Current State

The current verified state is:

- Cloud addon is installed and active on `npcink.local`.
- Addon Save and Verify succeeded.
- Dedicated Cloud identity is provisioned.
- Runtime resolve works.
- Runtime execute works.
- The guarded trial chain is complete.
- The repository worktree was clean after the final execution.

This phase is done.

## Recommendation

Stop here for this phase.

Do not automatically continue into Site Knowledge, monitoring, or WordPress
content writes. Those are separate phases with different blast radius and must
have their own approval gates and evidence chain.

The next possible phase, if desired, is a separate Site Knowledge decision:

- define whether the goal is sync, search, or both;
- define exact content sampling boundaries;
- confirm no WordPress writes;
- create a prepare-only packet before any execution;
- require exact approval text before any sync/search.

## Handoff For Future Agents

If continuing from this record:

1. Treat `.tmp/live-site-trial-status/npcink-after-execute/trial-status-report.json`
   as the closeout evidence for this phase.
2. Do not rerun Stage 1 unless intentionally testing idempotency or rollback.
3. Do not run Site Knowledge or monitoring based on this closeout.
4. Preserve the Cloud boundary: runtime/detail only, not a second WordPress
   control plane.
5. If new runtime evidence is needed, create a new dated output directory
   instead of overwriting this closeout evidence.
