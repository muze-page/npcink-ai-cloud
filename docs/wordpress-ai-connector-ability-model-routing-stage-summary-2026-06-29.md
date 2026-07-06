# WordPress AI Connector Ability-Model Routing Stage Summary

Status: stage closeout summary.
Date: 2026-06-29.

## Summary

This stage established and verified the Cloud-side **ability-model routing**
path for WordPress AI Connector tasks.

The local development chain has been verified end to end:

```text
magick-ai.local WordPress plugin
-> npcink-cloud-addon
-> local Cloud http://127.0.0.1:8010
-> wp-ai.short-text
-> openai-global-gpt-5-5
```

Production is not yet closed out. The repository now has a production smoke
helper and runbook so the same path can be verified after deploying Cloud to:

```text
https://cloud.npc.ink/
```

## Boundary

Cloud remains the hosted runtime enhancement layer.

Cloud owns:

- runtime profile routing;
- provider/model execution;
- usage and provider-call evidence;
- routing health and diagnostics;
- service-plane audit evidence.

WordPress/plugin side remains the source of truth for:

- ability identity and schema;
- prompt and preset truth;
- local approval and preflight;
- audit truth for local decisions;
- final WordPress writes.

This stage did not add a Cloud ability registry, prompt editor, workflow
registry, approval system, or WordPress write owner.

## Landed Commits

Relevant commits in this stage:

```text
0fd6051 Codify ability-model routing boundary
26e6715 Preserve routing intent on connector runs
478c48c Retry OpenAI responses without unsupported metadata
12e5e0c Add production WordPress AI connector smoke
```

## What Changed

### Ability-Model Routing Contract

Added the Cloud contract:

```text
docs/cloud-ability-model-routing-v1.md
```

The admin concept is **Ability-model routing** / **能力-模型路由**.

Current WordPress AI Connector routing groups:

```text
content.short_text        -> wp-ai.short-text
content.editorial         -> wp-ai.editorial
content.classification    -> wp-ai.classification
media.image_generation    -> wp-ai.image-generation
```

The contract explicitly forbids Cloud persistence of local-control-plane fields
such as prompts, presets, approval policy, apply policy, final write policy,
required scopes, and WordPress write targets.

### Runtime Evidence

Runtime now preserves routing intent for managed WordPress AI Connector runs:

```text
policy_json.routing_intent
policy_json.execution_contract.routing_intent
```

This applies to both:

- text connector runs such as `title_generation`;
- WordPress AI Connector image-generation runtime requests.

### Provider Compatibility

Real Cloud execution exposed two operational issues:

1. `wp-ai.short-text` initially selected an invalid first candidate:

   ```text
   openai-global-funaudiollm-sensevoicesmall
   ```

   The local dev routing binding was corrected through the internal Admin
   route to prefer:

   ```text
   openai-global-gpt-5-5
   ```

2. The OpenAI-compatible upstream rejected `metadata` on the Responses API:

   ```text
   provider.invalid_request: Unsupported parameter: metadata
   ```

   The provider adapter now retries once without `metadata` only when the
   upstream explicitly reports that parameter as unsupported. Cloud run policy
   and internal evidence still keep the routing metadata.

### Production Smoke Helper

Added:

```text
app/dev/production_wordpress_ai_connector_smoke.py
tests/dev/test_production_wordpress_ai_connector_smoke.py
docs/production-wordpress-ai-connector-smoke-runbook-v1.md
```

The helper defaults to safe checks:

- `GET /health/live`;
- signed image-generation `POST /v1/runtime/resolve`;
- no title execute;
- no image execute;
- no WordPress write.

Title generation execute requires:

- `--execute-title`;
- the exact approval text documented in the runbook.

## Local Verification Evidence

### Cloud Runtime Direct Smoke

Local Cloud direct signed title execution succeeded:

```text
run_id=run_fd53290980eb496e8e46c4c4c539debd
profile_id=wp-ai.short-text
selected_model_id=gpt-5.5
selected_instance_id=openai-global-gpt-5-5
routing_intent=content.short_text
status=succeeded
```

Provider-call evidence:

```text
provider_id=openai
model_id=gpt-5.5
instance_id=openai-global-gpt-5-5
```

Image route resolve succeeded without image execution:

```text
profile_id=wp-ai.image-generation
execution_kind=image_generation
selected_instance_id=openai-global-grok-imagine-image-quality
routing_intent=media.image_generation
```

### magick-ai.local WordPress Plugin Smoke

The correct local test site is:

```text
https://magick-ai.local/
```

`npcink.local` was only a temporary earlier trial target and should not be used
as the acceptance target for this stage.

The magick-ai.local plugin chain is active:

```text
npcink-cloud-addon
npcink-abilities-toolkit
npcink-ai-client-adapter
npcink-governance-core
npcink-workflow-toolbox
```

Cloud addon settings on magick-ai.local were verified against local Cloud:

```text
base_url=http://127.0.0.1:8010
site_id=site_magick-ai-local
wp_ai_connector_connected=1
```

WordPress plugin helper execution succeeded:

```text
run_id=run_9f3cdfc813214ba385a9255f86abe5e5
site_id=site_magick-ai-local
ability_name=npcink-cloud/wp-ai-connector
channel=wordpress_ai_connector
execution_kind=text
profile_id=wp-ai.short-text
selected_model_id=gpt-5.5
selected_instance_id=openai-global-gpt-5-5
routing_intent=content.short_text
status=succeeded
```

Output preview:

```text
Crafting the Perfect WordPress Post Title
```

## Verification Commands Run

Focused tests:

```bash
.venv/bin/python -m pytest tests/api/test_wordpress_ai_connector_runtime.py
.venv/bin/python -m pytest tests/domain/test_openai_provider.py
.venv/bin/python -m pytest tests/dev/test_production_wordpress_ai_connector_smoke.py
```

Syntax and whitespace checks:

```bash
.venv/bin/python -m py_compile app/dev/production_wordpress_ai_connector_smoke.py
git diff --check -- app/dev/production_wordpress_ai_connector_smoke.py tests/dev/test_production_wordpress_ai_connector_smoke.py
git diff --check -- docs/production-wordpress-ai-connector-smoke-runbook-v1.md docs/cloud-ability-model-routing-v1.md
```

Earlier standard gate:

```bash
pnpm run check:fast
```

At the time it was run, contract and domain checks passed.

## Operational Notes

### Local WP-CLI for magick-ai.local

System `wp` needs Local's MySQL socket:

```bash
WP_PATH="/Users/muze/Local Sites/magick-ai/app/public"
WP_URL="https://magick-ai.local/"
WP_SOCKET="/Users/muze/Library/Application Support/Local/run/NPb24Zg9g/mysql/mysqld.sock"

php -d mysqli.default_socket="$WP_SOCKET" "$(which wp)" \
  --path="$WP_PATH" \
  --url="$WP_URL" \
  plugin list --fields=name,status,version --format=table
```

Without the socket override, WP-CLI may fail with:

```text
Error establishing a database connection.
```

### Stale Queued Runs

Two smoke attempts were initially blocked by:

```text
commercial.concurrency_exceeded
```

Cause: stale queued Site Knowledge sync runs counted against the per-site
active-run limit.

Resolution used signed runtime cancel for confirmed stale dev/smoke runs before
retrying. Do not directly edit production DB state for this condition.

### Docker Hub Timeout

The local dev API container mounts source with `--reload`, so the provider
adapter fix became active locally without rebuilding the Docker image. This does
not replace production deployment; production still needs the updated code
released normally.

## Production Closeout Plan

Production is ready for validation after deploy, but not yet validated.

Use:

```text
docs/production-wordpress-ai-connector-smoke-runbook-v1.md
```

Sequence:

1. Deploy current Cloud code to production.
2. Confirm production `wp-ai.short-text` routes to a valid text instance.
3. Confirm production `wp-ai.image-generation` routes to a valid image instance.
4. Issue or locate the production site key for the target site.
5. Run safe resolve smoke:

   ```bash
   .venv/bin/python -m app.dev.production_wordpress_ai_connector_smoke \
     --secret-file .tmp/prod-cloud-api-key.secret.json \
     --base-url https://cloud.npc.ink
   ```

6. If resolve passes, run title execute with the exact approval text from the
   runbook.
7. Inspect production run evidence for:

   ```text
   ability_name=npcink-cloud/wp-ai-connector
   channel=wordpress_ai_connector
   execution_kind=text
   profile_id=wp-ai.short-text
   policy_json.routing_intent=content.short_text
   policy_json.execution_contract.routing_intent=content.short_text
   ```

## Current State

Completed:

- ability-model routing boundary documented;
- runtime `routing_intent` persistence landed;
- provider adapter compatibility fix landed;
- local Cloud direct smoke passed;
- magick-ai.local WordPress plugin smoke passed;
- production smoke helper and runbook landed.

Not completed:

- production deployment validation against `https://cloud.npc.ink/`;
- production run evidence capture;
- production WordPress addon base URL switch, if the test must be initiated
  from WordPress instead of the Cloud smoke helper.

## Handoff For Future AI

Do not reframe this as a Cloud ability registry or a Cloud WordPress control
plane. The correct framing is:

```text
Cloud ability-model routing = hosted runtime profile/model binding evidence.
WordPress plugin = ability/prompt/approval/write truth.
```

The next useful step is production validation with the runbook, not more local
product design.
