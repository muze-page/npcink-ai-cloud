# Real Site Trial Package - 2026-06-20

Status: ready for one controlled low-risk staging or clone target.

Purpose: define the next trial step after the local `wp-trial` runtime and
Site Knowledge rehearsals. This package is for a real site rehearsal with
reviewable assistance only. It is not a customer self-serve onboarding flow,
payment flow, Cloud publishing flow, or Cloud-side WordPress control plane.

## Current Evidence Baseline

Use this package only after reviewing these local rehearsal records:

- `docs/external-trial-candidate-preflight-wp-local-2026-06-19.md`
- `docs/external-trial-record-wp-trial-2026-06-19.md`
- `docs/external-trial-site-knowledge-wp-trial-2026-06-20.md`

The latest baseline proved:

- a dedicated Cloud site identity can be verified by the WordPress Cloud addon;
- hosted runtime execute / runs / usage / credit / billing detail can be traced;
- Site Knowledge can ingest a bounded public post/page subset;
- Site Knowledge search can return evidence-backed `writing_support_plan`;
- output stays `suggestion_only`;
- `direct_wordpress_write` remains false;
- WordPress remains the final write owner;
- Cloud data guard fails closed on suspicious payload fields.

## Trial Target Rule

Use a target in this order:

1. staging clone of a real site;
2. disposable clone of a real site;
3. low-risk live site only after an explicit second approval.

Do not use a high-traffic production site, revenue-critical site, regulated
advice site, or customer-owned live site as the first target.

The target must have:

- known WordPress root path and URL;
- known owner/operator;
- current backup path or restore point;
- `npcink-cloud-addon` installed and compatible;
- Cloud service reachable from the WordPress host;
- public post/page content that is safe to send as `public_site_content`;
- no requirement for Cloud to publish or mutate WordPress content.

## Explicit No-Write Boundary

Allowed in this trial:

- read WordPress site metadata and plugin state;
- read bounded public `post` / `page` excerpts;
- save and verify the Cloud addon key after backup/snapshot;
- run hosted runtime smoke;
- run Site Knowledge sync/search/status;
- inspect Cloud usage, credit, entitlement, billing/detail, runs, and errors;
- collect operator notes.

Not allowed in this trial:

- Cloud direct publishing;
- WordPress post/page mutation by Cloud;
- taxonomy, tag, category, menu, media, or option mutation outside the Cloud
  addon option;
- batch article generation;
- article body, article title, SEO copy, `article_write_plan`, full draft, or
  ready-to-publish output from Site Knowledge;
- Cloud prompt/router/workflow editor;
- Cloud skill registry;
- MCP platform behavior;
- customer self-serve payment or checkout.

Expected WordPress-side write:

- exactly one controlled Cloud addon settings write, after snapshot, to point
  the target site to the approved Cloud base URL and Cloud API key.

Expected Cloud-side writes:

- service-plane site/account/subscription/key records when provisioning is
  needed;
- run records;
- provider-call records;
- usage meter events;
- credit ledger entries;
- entitlement/billing/detail snapshots;
- Site Knowledge read-model rows for the target `site_id`.

## Preflight Checklist

Record these before changing anything:

- Date:
- Operator:
- Target environment: staging / clone / live
- WordPress URL:
- WordPress root path:
- Multisite: yes/no
- Backup or restore point:
- Existing Cloud addon verified: yes/no
- Existing Cloud addon site ID:
- Planned Cloud site ID:
- Declared use case:
- Content category review:
- Manual approval for live site if applicable: yes/no

Read-only WordPress checks:

```bash
wp --path="<wp-root>" option get siteurl
wp --path="<wp-root>" option get home
wp --path="<wp-root>" core version
wp --path="<wp-root>" plugin list --status=active --field=name
wp --path="<wp-root>" option get npcink_cloud_addon_settings --format=json
wp --path="<wp-root>" post list --post_type=post,page --post_status=publish --fields=ID,post_type,post_title,post_status,post_modified_gmt --format=table --posts_per_page=20
```

Do not print secrets from the addon option in shared notes. Redact `secret`,
customer-facing Cloud API keys, and any split credential values.

Cloud checks:

```bash
curl -sS "<cloud-base-url>/health/live"
docker compose -f docker-compose.dev.yml ps
```

For an external hosted Cloud environment, use the matching remote baseline
commands instead of local Docker commands:

```bash
bash deploy/remote-baseline-status.sh
bash deploy/remote-provider-status.sh
```

## Snapshot And Backup

Before the Cloud addon settings write, save the previous addon option:

```bash
mkdir -p .tmp/<trial-slug>
wp --path="<wp-root>" option get npcink_cloud_addon_settings --format=json > .tmp/<trial-slug>/npcink_cloud_addon_settings-before.json
chmod 600 .tmp/<trial-slug>/npcink_cloud_addon_settings-before.json
```

If the environment is live or shared staging, also require one of:

- hosting-provider snapshot;
- `wp db export` with a known working `mysqldump`;
- Local/host backup artifact with restore steps.

Do not continue if no rollback path exists.

## Provisioning

Provision through the existing service-plane path. Public runtime requests must
not implicitly create a site or key.

Minimum Cloud key scopes:

- `catalog:read`
- `runtime:resolve`
- `runtime:execute`
- `runtime:read`
- `stats:read`
- `entitlement:read`

Record:

- Account ID:
- Site ID:
- Subscription ID:
- Plan:
- Plan version:
- Key ID:
- Key scopes:
- Key status:

Do not record the secret or customer-facing full Cloud API key in Git, shared
docs, screenshots, tickets, or logs.

## Addon Verification

After backup and provisioning, save the approved Cloud API key in the Cloud
addon and verify.

Expected post-save state:

- `base_url` matches the approved Cloud URL;
- `site_id` matches the provisioned Cloud site;
- `verified=true`;
- `last_verification_error` is empty;
- entitlement summary is available;
- addon local truth remains limited to hosted runtime access settings.

Block if:

- split credentials are exposed in WordPress UI;
- addon presents router, prompt, workflow, approval, or write controls;
- verification fails without a clear environment-only cause;
- any unrelated WordPress option, post, taxonomy, media, or user record changes.

## Runtime Smoke

Run one minimal hosted runtime request through the addon or signed runtime
client.

Record:

- Run ID:
- Status:
- Provider ID:
- Model ID:
- Fallback used:
- Usage meter updated: yes/no
- Credit ledger updated: yes/no
- Billing/detail snapshot refreshed: yes/no

Required pass condition:

- status is succeeded;
- result is read-only;
- no WordPress content changed.

## Site Knowledge Rehearsal

Extract a bounded public content subset:

- use public `post` and `page` only;
- default limit: 5 to 20 documents;
- exclude drafts, private posts, users, comments, author email, IP address,
  user agent, payment/contact identifiers, credentials, admin URLs, and raw
  private metadata;
- use stable non-PII content refs for runtime `content_hash` fields, such as
  `site-slug-doc-a`, rather than SHA-256-like numeric-heavy strings.

Required runtime calls:

- `npcink-cloud/site-knowledge-sync`
- `npcink-cloud/site-knowledge-search`
- `npcink-cloud/site-knowledge-status`

Required search posture:

- `intent`: `writing_support_plan`, `writing_context`, `site_search`, or
  another supported Site Knowledge intent;
- `write_posture`: `suggestion_only`;
- `data_classification`: `public_site_content`;
- `storage_mode`: `result_only`;
- `evidence_policy.no_hit_policy`: `abstain`.

Required pass condition:

- sync succeeds or fails closed with a specific Cloud error;
- status reports indexed chunks when sync succeeds;
- search response includes `evidence_gate`;
- when `evidence_gate.status=passed`, results contain source references;
- when `evidence_gate.status=insufficient_evidence`, no site-specific claims
  are invented;
- `direct_wordpress_write=false`;
- handoff owner is `wordpress_local` when `agent_handoff` is present.

## Evidence Record Template

Create one trial record under `docs/` after the run.

```markdown
# Real Site Trial Record - <slug> - <date>

Status:

## Target

- Environment:
- WordPress URL:
- WordPress root path:
- Cloud base URL:
- Site ID:
- Account ID:
- Subscription ID:
- Key ID:
- Declared use case:
- Backup path:

## Boundary

- WordPress source posture:
- Runtime write posture:
- Direct WordPress write:
- Direct publishing:
- Batch article generation:
- Cloud prompt/router/workflow editor:
- Cloud skill registry or MCP platform:

## Addon Verification

- Before snapshot path:
- Verified:
- Verified at:
- Entitlement available:
- Last verification error:

## Runtime Smoke

- Run ID:
- Status:
- Provider:
- Model:
- Fallback:
- Usage:
- Credits:
- Billing/detail:

## Site Knowledge

- Sync run ID:
- Search run ID:
- Status run ID:
- Indexed documents:
- Indexed chunks:
- Search intent:
- Evidence gate:
- Result count:
- Top sources:
- Write posture:
- Direct WordPress write:
- Handoff owner:

## Guardrails

- PII/secret guard findings:
- Blocked outputs:
- WordPress content changed:
- Non-addon options changed:
- Rollback tested:

## Decision

- Go/no-go:
- Blockers:
- Next action:
```

## Rollback

Rollback order:

1. Stop the trial for the target site.
2. Revoke or suspend the Cloud API key through service-plane operations.
3. Restore previous Cloud addon settings from the option snapshot.
4. Verify the addon no longer authenticates with the revoked key.
5. Leave Cloud run/usage/credit evidence intact for audit unless a separate
   data-retention decision says otherwise.
6. Record rollback evidence in the trial record.

Addon option restore:

```bash
wp --path="<wp-root>" option update npcink_cloud_addon_settings "$(cat .tmp/<trial-slug>/npcink_cloud_addon_settings-before.json)" --format=json
```

Use a staging/clone restore point instead of manual DB edits if any unexpected
WordPress content mutation is observed.

## Go / No-Go Criteria

Go for a second controlled target only if all are true:

- Cloud addon verifies against the intended site identity;
- runtime smoke succeeds;
- Site Knowledge sync/search/status succeeds or fails closed for a clear
  payload/category reason;
- `suggestion_only` is preserved;
- `direct_wordpress_write=false` is preserved;
- usage, credit, entitlement, and billing/detail evidence are inspectable;
- rollback path is available and documented;
- no forbidden Cloud control-plane surface is introduced.

No-go if any are true:

- target is live and lacks explicit second approval;
- backup/restore path is missing;
- provider or Cloud keys appear in WordPress UI, logs, docs, or screenshots;
- Site Knowledge returns article body, article title, SEO copy,
  `article_write_plan`, full draft, ready-to-publish content, or automatic
  publishing instructions;
- Cloud mutates WordPress content or taxonomy;
- evidence cannot identify site, run, usage, credit, and error details;
- trial pressure suggests adding Cloud router/prompt/workflow controls.

## Recommended Next Target

Use a staging or clone target first. If only live local sites are available,
clone one of them before the run. The next operational step is to fill the
Preflight Checklist for one candidate and stop before the addon settings write
until the candidate, backup path, and rollback path are confirmed.
