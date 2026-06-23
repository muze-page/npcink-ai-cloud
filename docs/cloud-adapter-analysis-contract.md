# Cloud Adapter Analysis Contract

Status: active contract
Date: 2026-05-30

## Purpose

This document is the **copy-paste reference** for `magick-ai-adapter` when calling Cloud-hosted analysis through the existing runtime surface.

Cloud does **not** expose a separate `/v1/analysis/*` execution lane in phase one. Adapter reuses:

- `POST /v1/runtime/execute`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/result`
- `GET /v1/stats/*`

## Auth and Transport

Use the same HMAC site-key signing as all other public runtime calls.

Required headers:

```http
X-Npcink-Site-Id: <site_id>
X-Npcink-Key-Id: <key_id>
X-Npcink-Timestamp: <unix-seconds>
X-Npcink-Nonce: <nonce>
X-Npcink-Trace-Id: <trace-id>
X-Npcink-Signature: <hmac-sha256-signature>
Idempotency-Key: <idempotency-key>
traceparent: <traceparent>   # optional but recommended
```

## Recommended Runtime Payload Defaults for Analysis

```json
{
  "site_id": "<site_id>",
  "ability_name": "openclaw/analysis/<site-specific-name>",
  "ability_family": "openclaw",
  "execution_kind": "text",
  "execution_tier": "cloud",
  "execution_pattern": "whole_run_offload",
  "storage_mode": "result_only",
  "data_classification": "internal",
  "profile_id": "text.free-gpt55",
  "idempotency_key": "<uuid>",
  "trace_id": "<trace-id>",
  "input": {
    "messages": [
      {
        "role": "user",
        "content": "<prompt>"
      }
    ],
    "proposal_id": "<proposal-id>",
    "correlation_id": "<correlation-id>",
    "external_thread_id": "<external-thread-id>",
    "openclaw_thread_id": "<openclaw-thread-id>"
  },
  "policy": {
    "allow_fallback": true
  }
}
```

Field rules:

- `ability_family` must be `"openclaw"` for Cloud to apply the analysis result envelope.
- `execution_pattern` should be `"whole_run_offload"` for queue-backed analysis; `"inline"` is acceptable for small fast queries.
- `policy` may **only** contain `"allow_fallback"`. All local-governance keys (`requires_confirm`, `tool_policy`, `approval_policy`, `apply_policy`, `final_write_policy`, `wordpress_write_policy`, `write_control`, etc.) are rejected with `422`.
- Correlation ids (`proposal_id`, `correlation_id`, `external_thread_id`, `openclaw_thread_id`) should live inside `input` so they are preserved in the run record and echoed back in `proposal_handoff`.

## Execute Response Shape

The execute response reuses the existing runtime envelope. Key fields for Adapter:

```json
{
  "status": "ok",
  "data": {
    "run_id": "run_<uuid>",
    "status": "queued" | "running" | "succeeded",
    "trace_id": "<trace-id>",
    "execution_context": {
      "ability_family": "openclaw",
      "execution_tier": "cloud",
      "execution_pattern": "whole_run_offload",
      "storage_mode": "result_only"
    },
    "result": { ... }
  }
}
```

## Status Polling

```http
GET /v1/runs/{run_id}
```

Returns run metadata. Adapter can poll `status` until it reaches `succeeded`, `failed`, or `canceled`.

## Result Retrieval

```http
GET /v1/runs/{run_id}/result
```

Returns the full result envelope:

```json
{
  "status": "ok",
  "data": {
    "run_id": "run_<uuid>",
    "status": "succeeded",
    "execution_context": { ... },
    "result": {
      "analysis_type": "report" | "recommendation" | "proposal_input",
      "summary": "...",
      "findings": [],
      "recommendations": [],
      "requires_local_approval": false | true,
      "proposal_handoff": {
        "proposal_id": "...",
        "correlation_id": "...",
        "external_thread_id": "...",
        "openclaw_thread_id": "..."
      },
      "_cloud_raw_result": { ... }
    }
  }
}
```

## Analysis Envelope Fields

| Field | Meaning |
| --- | --- |
| `analysis_type` | `"report"` for read-only; `"proposal_input"` when the output implies a WordPress mutation |
| `summary` | Short human-readable summary of the provider output |
| `findings` | Structured findings list (empty in phase one if provider returned free text) |
| `recommendations` | Structured recommendations (empty in phase one if provider returned free text) |
| `requires_local_approval` | `true` whenever the analysis implies a mutation or contains write-completion language |
| `proposal_handoff` | Correlation ids from Adapter input, ready for Core proposal creation |
| `_cloud_raw_result` | Sanitized provider metadata / debug metadata; dangerous text fields are removed when write-completion language is detected |

## Write-Like Recommendation Constraint

Cloud **must not** claim that a WordPress write has already been applied.

If the provider output contains language like:

- "written to WordPress"
- "changes applied"
- "product updated"
- "已写入 WooCommerce"

Cloud sets:

```json
{
  "requires_local_approval": true,
  "analysis_type": "proposal_input"
}
```

The actual WordPress mutation is created by `magick-ai-core` as a governed proposal; Cloud only returns the proposal-ready artifact.

When write-completion language is detected, the public response **must not** expose the dangerous provider original text. `_cloud_raw_result` is sanitized: fields such as `output_text` and `messages` are stripped, while safe metadata (`model_id`, `usage`, `finish_reason`, `provider`, `latency_ms`) may be retained.

## Removed Surfaces

These URLs remain absent and return `404`:

- `/v1/task-packs/*`
- `/v1/orchestration/*`
- `/v1/addon/*`
- `/v1/prompt/*/recommendation`
- `/v1/preset/*/recommendation`

Do not build Adapter logic that depends on them.

## Error Codes Adapter Should Handle

| Code | HTTP | Meaning |
| --- | --- | --- |
| `auth.invalid_site` | 401 | Site not provisioned |
| `auth.invalid_key` | 401 | Key revoked or expired |
| `auth.replay_blocked` | 409 | Reused nonce |
| `auth.rate_limit_exceeded` | 429 | Too many requests |
| `runtime.idempotency_conflict` | 409 | Same idempotency key, different payload |
| `commercial.subscription_inactive` | 403 | Subscription not active |
| `commercial.entitlement_denied` | 403 | Ability family or execution kind not entitled |
| `commercial.quota_exceeded` | 429 | Budget exhausted |
| `commercial.concurrency_exceeded` | 429 | Too many active queued runs |
| `runtime.result_not_ready` | 409 | Run not finished yet |
| `runtime.result_expired` | 410 | Result purged by retention policy |

## Assumptions

- Adapter is responsible for assembling local WordPress context into `input`.
- Adapter is responsible for creating Core proposals from `proposal_handoff`.
- Cloud does not call WordPress directly.
- Cloud durable run truth lives in `RunRecord` and `/v1/runs/*` only.
