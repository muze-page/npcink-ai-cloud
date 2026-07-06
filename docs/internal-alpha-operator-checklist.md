# Internal Alpha Operator Checklist

Status: active internal reference
Date: 2026-05-28
Scope: local alpha runtime/ops minimum hardening

## Purpose

This checklist turns the automated `operator_guidance` from runtime diagnostics into
bounded, human-readable operator actions. It is not a new Cloud control plane; it is a
read-only diagnosis companion that stays inside the existing service-plane evidence.

## How to use this checklist

1. Run `pnpm run smoke:internal-alpha-onboarding` to confirm the Admin to Portal
   onboarding contract.
2. Run `pnpm run smoke:local-alpha` to capture current environment evidence.
3. Inspect `operator_guidance` in the evidence file (or via `GET /internal/service/runtime/diagnostics/summary`).
4. Match `primary_reason` to the section below and follow the bounded actions.
5. Record what you observed; do not attempt repairs outside the listed scope.

## Guidance-to-action mapping

### `healthy`

- **What it means**: No primary blocker detected.
- **Evidence path**: `operator_guidance.state` is `healthy`.
- **Operator action**: No immediate action required.
- **Recording**: Keep the smoke/drill evidence file path for the baseline record.

### `provider_failures`

- **What it means**: The dominant error stage is `provider`.
- **Evidence path**: `failures.dominant_error`
- **Operator action**:
  1. Read `failures.dominant_error.error_code` and `provider_id`.
  2. Verify provider credentials, quota, and health:
     - `pnpm run drill:provider-failure` (isolated fake-provider drill)
     - `GET /internal/service/runtime/diagnostics/summary` → `failures`
     - `GET /internal/service/runtime/diagnostics/runs?status=failed&limit=20`
  3. If the provider is DeepSeek or another OpenAI-compatible adapter, confirm
     the corresponding `/admin/ai-resources` provider connection is configured,
     tested, and not rate-limited.
- **Do not**: change provider adapter code during the drill; use the drill to confirm
  whether the issue is credential/quota vs. adapter behavior.

### `callback_delivery`

- **What it means**: Terminal callback dispatch is failing or under pressure.
- **Evidence path**: `callback.pressure_reasons`
- **Operator action**:
  1. Read `callback.failed`, `callback.overdue`, and `callback.dispatching_stale`.
  2. Verify callback URL reachability from the Cloud network.
  3. Run `pnpm run drill:callback-failure` to confirm the callback-failure path
     produces the expected `primary_reason=callback_delivery` guidance.
  4. Check `callback-worker` heartbeat in ops cadence:
     - `GET /internal/service/ops/cadence` → look for `callback-worker`
- **Do not**: change WordPress callback endpoint code during the drill; the drill
  uses an isolated fake callback and does not call WordPress.

### `runtime_queue`

- **What it means**: Queued or running runs are backing up.
- **Evidence path**: `queue.pressure_reasons`
- **Operator action**:
  1. Read `queue.queued`, `queue.running`, `queue.queued_stale`, `queue.running_stale`.
  2. Check worker heartbeat:
     - `GET /internal/service/ops/cadence` → `worker` and `callback-worker`
  3. If `queue.pressure_state` is `critical`, inspect whether the worker container
     is running and whether Redis is reachable from the worker.
- **Do not**: introduce a new scheduler or queue truth; the current queue is
  Redis-wake-up + `run_records` source of truth.

### `cancel_requests`

- **What it means**: Cancel requests are stuck or accumulating.
- **Evidence path**: `cancel.pressure_reasons`
- **Operator action**:
  1. Read `cancel.stuck` and `cancel.recent`.
  2. Inspect cancel diagnostics runs:
     - `GET /internal/service/runtime/diagnostics/runs?status=canceled&limit=20`
  3. Verify that `POST /v1/runs/{run_id}/cancel` returns correctly for queued runs.
- **Do not**: attempt provider-level hard abort; running cancel is best-effort at
  worker attempt boundaries.

### `auth/guard`

- **What it means**: Abuse guard or runtime guard events are elevated.
- **Evidence path**: abuse guard diagnostics, runtime guard events
- **Operator action**:
  1. Read `GET /internal/service/runtime/diagnostics/abuse-guard` for:
     - `attention_ratio`, `critical_ratio`
     - recent rate-limit, replay-block, payload-too-large, invalid-nonce counts
  2. Read `GET /internal/service/runtime/diagnostics/guard-events` for recent
     `runtime_guard_events` by `scope_kind` and `event_type`.
  3. Run `pnpm run drill:auth-failure` to confirm the auth-reject path produces
     the expected `401` + `auth.invalid_signature` response and that guard events
     capture the reject evidence.
  4. If a specific site or key is responsible, verify its signing secret and
     request header construction (timestamp, nonce, canonical request).
- **Do not**: disable guard rules globally; investigate per-scope patterns first.

## Evidence directory conventions

- Local alpha smoke: `.tmp/local-alpha-smoke/`
- Provider failure drill: `.tmp/local-alpha-provider-failure-drill/`
- Callback failure drill: `.tmp/local-alpha-callback-failure-drill/`
- Auth failure drill: `.tmp/local-alpha-auth-failure-drill/`

These directories are gitignored. Only record the path in baseline docs, never
commit evidence files.

## Deferred operator surfaces

The following remain intentionally deferred to a separate release-phase decision:

- automated remediation playbooks beyond bounded suggested actions
- customer-visible incident status pages
- real-time pager/alert integrations
- multi-region failover runbooks
