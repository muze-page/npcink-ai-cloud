# Production WordPress AI Connector Smoke Runbook v1

Status: active.
Updated: 2026-07-15.

P1-E05 status: operator-only pending. This runbook and its local builder tests
are preparation, not evidence that the production title smoke passed.

P1-E06 status: operator-only pending. The pre-cutover inventory, backup, and
restore rehearsal are separate operator evidence and are not produced by this
smoke.

## Purpose

This runbook verifies the production Cloud runtime path for WordPress AI
Connector ability-model routing after deploying `npcink-ai-cloud`.

The smoke proves:

- production Cloud health is reachable;
- WordPress AI Connector image-generation routing can resolve without executing
  image generation;
- optional title generation execute can enter through
  `npcink-cloud/connector-runtime` and resolve to managed profile
  `wp-ai.short-text`;
- title execute evidence uses the current runtime fields for identity, provider
  execution, idempotency, errors, and the reviewable suggestion contract.

## Boundary

This smoke is Cloud runtime verification only.

Allowed:

- `GET /health/live`
- `POST /v1/runtime/resolve` for `wp-ai.image-generation`
- optional `POST /v1/runtime/execute` for `title_generation`
- durable Cloud run/provider evidence review

Forbidden:

- WordPress writes
- image generation execute
- Site Knowledge sync/search
- prompt, preset, approval, apply, or WordPress write policy changes
- creating a second Cloud ability registry or WordPress control plane

WordPress/plugin side remains the source of truth for ability identity, prompts,
approval, preflight, audit truth, and final WordPress writes.

## Files

Script:

```text
app/dev/production_wordpress_ai_connector_smoke.py
```

Tests:

```text
tests/dev/test_production_wordpress_ai_connector_smoke.py
```

Default output:

```text
.tmp/production-wordpress-ai-connector-smoke/production-wordpress-ai-connector-smoke-report.json
```

## Secret File

Create a local secret file after production Cloud has issued a site key.

Example path:

```text
.tmp/prod-cloud-api-key.secret.json
```

Expected shape:

```json
{
  "site_id": "site_xxx",
  "key_id": "key_xxx",
  "secret": "secret_xxx"
}
```

Do not commit this file. Do not paste the secret into tickets, docs, logs, or
chat output.

Set the canonical WordPress site URL and deployed connector version used by
both smoke modes:

```bash
export WORDPRESS_SITE_URL='https://wordpress.example.com'
export CONNECTOR_VERSION='1.0.0'
```

## Safe Resolve Smoke

Run this first after deploying production Cloud:

```bash
cd /Users/muze/gitee/npcink-ai-cloud

.venv/bin/python -m app.dev.production_wordpress_ai_connector_smoke \
  --secret-file .tmp/prod-cloud-api-key.secret.json \
  --base-url https://cloud.npc.ink \
  --site-url "$WORDPRESS_SITE_URL" \
  --connector-version "$CONNECTOR_VERSION"
```

This does:

- health check;
- signed image-generation `resolve` through the independent
  `image_generation_request.v1` contract;
- no title execute;
- no image execute;
- no WordPress write.

The safe image resolve intentionally remains separate from the neutral
connector title contract. It must not be rewritten to look like a WordPress
typed text operation.

Expected signals:

```text
ok=true
image_resolve.profile_id=wp-ai.image-generation
image_resolve.routing_intent=media.image_generation
image_resolve.selected_instance_id=<non-empty>
title_execute.skipped=true
```

If this fails, check:

- production service health;
- signed site/key status;
- `wp-ai.image-generation` routing binding;
- provider/model availability.

## Title Execute Smoke

Only run this after the safe resolve smoke passes.

Create the exact approval file:

```bash
cat > .tmp/prod-title-approval.txt <<'EOF'
我明确批准在正式 Cloud 运行一次 WordPress AI Connector 标题生成 execute smoke；本次不写 WordPress，不执行图片生成。
EOF
```

Run:

```bash
.venv/bin/python -m app.dev.production_wordpress_ai_connector_smoke \
  --secret-file .tmp/prod-cloud-api-key.secret.json \
  --base-url https://cloud.npc.ink \
  --site-url "$WORDPRESS_SITE_URL" \
  --connector-version "$CONNECTOR_VERSION" \
  --execute-title \
  --approval-file .tmp/prod-title-approval.txt
```

The title request uses one bounded, realistic
`operation_contract.request.source_text` value wrapped in `<content>` tags.
`request.prompt` is absent, as are `request.post_title` and
`request.post_excerpt`; this smoke does not exercise a compatibility shape.

Expected signals:

```text
ok=true
title_execute.run_id=<non-empty>
title_execute.trace_id=<non-empty>
title_execute.run_status=succeeded
title_execute.profile_id=wp-ai.short-text
title_execute.provider_id=<production text provider>
title_execute.model_id=<production text model>
title_execute.instance_id=<production text instance>
title_execute.provider_call_count>=1
title_execute.idempotent_replay=false
title_execute.error_code=<empty>
title_execute.error_stage=<empty>
title_execute.result_contract=cloud_connector_result.v1
title_execute.suggestion_only=true
title_execute.operation_contract_version=wordpress_operation.v1
title_execute.operation_task=title_generation
title_execute.output_text_preview=<non-empty>
```

Then inspect production Cloud run evidence and confirm:

```text
site_id=<expected site>
ability_name=npcink-cloud/connector-runtime
contract_version=cloud_connector_runtime.v1
channel=editor
execution_kind=text
run_id=<non-empty>
trace_id=<non-empty>
profile_id=wp-ai.short-text
provider_id=<production text provider>
model_id=<production text model>
instance_id=<production text instance>
provider_call_count>=1
idempotent_replay=false
error_code=<empty>
error_stage=<empty>
policy_json.routing_intent=content.short_text
policy_json.execution_contract.routing_intent=content.short_text
result.contract_version=cloud_connector_result.v1
result.suggestion_only=true
result.operation_contract.contract_version=wordpress_operation.v1
result.operation_contract.task=title_generation
result.output.output_text=<non-empty reviewable suggestion>
```

Also confirm that the request input used the canonical site and connector
fields (`site_url`, `platform_kind=wordpress`,
`connector_id=npcink-cloud-addon`, `connector_version`, and
`suggestion_only=true`) and that no WordPress write or approval event was
created by Cloud.

The report must retain the returned run/provider evidence without secrets. A
real P1-E05 record must additionally attach operator-reviewed idempotency
evidence; one successful builder or execute test does not prove replay
behavior. Do not mark P1-E05 complete from local pytest output.

## Local Test Gate

Before changing this smoke helper, run:

```bash
.venv/bin/python -m pytest tests/dev/test_production_wordpress_ai_connector_smoke.py
.venv/bin/python -m py_compile app/dev/production_wordpress_ai_connector_smoke.py
git diff --check -- app/dev/production_wordpress_ai_connector_smoke.py tests/dev/test_production_wordpress_ai_connector_smoke.py
```

## Failure Notes

`commercial.concurrency_exceeded` means the site has an active queued,
processing, or running Cloud run. Inspect production run state before retrying.
Cancel only confirmed stale dev/smoke runs through the approved runtime
operations path.

`auth.invalid_key` means the site key is missing, revoked, expired, signed with
the wrong secret, or pointed at the wrong Cloud environment.

`provider.invalid_request` means routing reached provider execution but the
selected provider/model rejected the payload. Check the provider adapter and
production routing binding before changing WordPress plugin behavior.
