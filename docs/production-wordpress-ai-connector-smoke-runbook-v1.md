# Production WordPress AI Connector Smoke Runbook v1

Status: active.
Date: 2026-06-29.

## Purpose

This runbook verifies the production Cloud runtime path for WordPress AI
Connector ability-model routing after deploying `npcink-ai-cloud`.

The smoke proves:

- production Cloud health is reachable;
- WordPress AI Connector image-generation routing can resolve without executing
  image generation;
- optional title generation execute can run through `wp-ai.short-text`;
- runtime evidence includes the expected profile and routing intent.

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

## Safe Resolve Smoke

Run this first after deploying production Cloud:

```bash
cd /Users/muze/gitee/npcink-ai-cloud

.venv/bin/python -m app.dev.production_wordpress_ai_connector_smoke \
  --secret-file .tmp/prod-cloud-api-key.secret.json \
  --base-url https://cloud.npc.ink
```

This does:

- health check;
- signed image-generation `resolve`;
- no title execute;
- no image execute;
- no WordPress write.

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
  --execute-title \
  --approval-file .tmp/prod-title-approval.txt
```

Expected signals:

```text
ok=true
title_execute.run_status=succeeded
title_execute.profile_id=wp-ai.short-text
title_execute.output_text_preview=<non-empty>
```

Then inspect production Cloud run evidence and confirm:

```text
site_id=<expected site>
ability_name=npcink-cloud/wp-ai-connector
channel=wordpress_ai_connector
execution_kind=text
profile_id=wp-ai.short-text
selected_model_id=<production text model>
selected_instance_id=<production text instance>
policy_json.routing_intent=content.short_text
policy_json.execution_contract.routing_intent=content.short_text
```

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
