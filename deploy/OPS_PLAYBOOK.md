# Cloud Ops Playbook

> Status: active
>
> Updated: 2026-04-15
>
> Scope: standalone `npcink-ai-cloud` production operations, cadence recovery, addon projection-first runbook, release-time troubleshooting

## Purpose

This playbook is the minimum operator contract for Npcink AI Cloud production work.
If a release depends on manual knowledge that is not written here, the release is not closed.

Primary internal checkpoints:

- `GET /health/live`
- `GET /health/ready`
- `GET /health/operational-ready`
- `GET /internal/service/observability/summary`
- `GET /internal/service/ops/cadence`
- `GET /internal/service/runtime/diagnostics/summary`
- `GET /internal/service/runtime/diagnostics/backlog`
- signed `GET /v1/addon/dashboard`
- signed `GET /v1/addon/providers/release-summary`

## Addon Projection Semantics

The addon overview and provider release summary are now `projection-first + live fallback`.

Operator interpretation rules:

- `source=projection`: Cloud is serving the managed site projection.
- `source=live_fallback`: Cloud could not use the projection and rebuilt the summary live.
- `stale=false`: the summary is still inside the Cloud freshness window.
- `stale=true`: the returned summary is outside the freshness window and should be treated as attention-worthy.
- `fallback_reason=projection_missing`: cadence has not produced the projection yet.
- `fallback_reason=projection_stale`: cadence output exists but is too old, so Cloud rebuilt live.
- `fallback_reason=projection_error`: Cloud could not read the stored projection and rebuilt live.
- release smoke now requires addon credentials; missing `site_id / key_id / secret` is itself a release-blocking configuration error.

Manual refresh guidance:

- WordPress "刷新云端数据" refreshes the local short cache only.
- WordPress "刷新发布证据" refreshes the local cached read of Cloud provider evidence only.
- Neither button changes Cloud truth or forces a projection rebuild job.
- If repeated reads keep returning `live_fallback`, inspect `ops-worker` and cadence freshness instead of relying on repeated local refresh clicks.

## Secret Rotation

### Admin bootstrap token

1. Generate a new `NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN`.
2. Update the deploy secret store.
3. Restart `api`.
4. Verify `POST /admin/auth/bootstrap` succeeds with the new token and fails with the old token.
5. Record the rotation window in operator notes.

### Internal service token

1. Generate a new `NPCINK_CLOUD_INTERNAL_AUTH_TOKEN`.
2. Update the deploy secret store for `api`, `frontend`, `worker`, `callback-worker`, and `ops-worker`.
3. Restart those services together.
4. Verify `GET /health/ready` and `GET /internal/service/observability/summary` with the new token.
5. Verify old-token requests fail closed.

### Session invalidation

1. Rotate `NPCINK_CLOUD_ADMIN_SESSION_SECRET` to invalidate `/admin/*` sessions.
2. Rotate `NPCINK_CLOUD_PORTAL_JWT_SECRET` to invalidate `/portal/*` sessions.
3. Restart `api` and `frontend`.
4. Verify stale cookies no longer access `/admin/session` or `/portal/v1/session`.

## Worker Operations

### Restart workers

Run on the release host:

```bash
cd /opt/npcink-ai-cloud
COMPOSE_PROJECT_NAME="${NPCINK_CLOUD_COMPOSE_PROJECT_NAME:-npcink-ai-cloud}" \
  docker compose -f docker-compose.prod.yml restart worker callback-worker ops-worker
```

Then verify:

- `GET /health/operational-ready` returns `200`
- `GET /internal/service/observability/summary` shows fresh worker heartbeats
- `GET /internal/service/ops/cadence` shows non-fresh tasks recovering toward fresh

### Callback backlog recovery

1. Check `GET /internal/service/observability/summary`.
2. Inspect `runtime.summary.callback` and `runtime.backlog`.
3. If `callback.dispatching_stale` or overdue callbacks persist, restart `callback-worker`.
4. Recheck `/internal/service/runtime/diagnostics/runs?issue_kind=callback_overdue`.
5. Confirm backlog declines before broader intervention.

### Manual retention cleanup

Use only when cadence is stale or blocked:

```bash
curl -X POST "$NPCINK_CLOUD_BASE_URL/internal/service/runtime/retention/cleanup" \
  -H "X-Npcink-Internal-Token: $NPCINK_CLOUD_INTERNAL_AUTH_TOKEN" \
  -H "Idempotency-Key: manual-retention-cleanup-$(date +%s)"
```

Then verify:

- `GET /internal/service/ops/cadence`
- `GET /internal/service/audit-events?event_kind=runtime.retention_cleanup&limit=5`

## Database Rollback

1. Confirm the target backup artifact exists before release.
2. Stop write traffic if rollback is required.
3. Restore the known-good database snapshot using the host-specific restore procedure.
4. Restart `api`, `worker`, `callback-worker`, and `ops-worker`.
5. Verify `/health/ready` and `/internal/service/observability/summary`.

## Provider Failover

1. Inspect `providers.degraded_provider_ids` in `GET /internal/service/observability/summary`.
2. Cross-check `alert.provider_degradation_cadence` freshness in `GET /internal/service/ops/cadence`.
3. Update provider routing/connection state from the local plugin control plane, not from Cloud.
4. Confirm the selected provider for the release host has a real credential configured before retrying runtime smoke.
5. Re-run one real runtime request and confirm provider health recovers in the next cadence window.

If real runtime smoke returns `runtime.provider_not_configured`, treat it as a release-blocking environment failure, not as a soft smoke warning.

## Cadence Stale Recovery

1. Check `GET /health/operational-ready`.
2. Inspect `GET /internal/service/ops/cadence`.
3. If one or more tasks are stale, restart `ops-worker`.
4. If staleness persists, inspect `service_audit_events` for the failing cadence task.
5. If addon projection reads are falling back, confirm both of these cadence tasks are fresh:
   - `addon_overview_projection`
   - `provider_release_summary_projection`
6. Re-run signed addon reads and confirm `source=projection` returns again, or that `live_fallback` at least carries an explicit `fallback_reason`.
7. After recovery, verify `non_fresh_total == 0`.

## Trace Sink Check

1. Read `data.tracing.trace_sink_otlp_endpoint` and `data.tracing.trace_sink_query_url` from `GET /internal/service/observability/summary`.
2. Open the configured query URL or trace UI.
3. Trigger a fresh internal request such as `GET /health/operational-ready`.
4. Confirm a new trace for `npcink-ai-cloud` appears in the sink.
5. If the collector is reachable but no trace lands in the sink, the release is not closed.

## Release Gate

Before a formal release, operators must start from `deploy/RELEASE_CHECKLIST.md`.

The release gate is divided into:

- repo ready
- env required
- operator required
- smoke required

`repo ready` can be closed by repository evidence. `env required`, `operator required`, and `smoke required` must be closed on the actual release host. If any item in those categories is incomplete, the release is blocked.

`deploy/release-smoke.sh` is the formal smoke gate. Do not replace it with a second release entry point or a partial manual checklist.

Operators must be able to answer all of these from current data:

- Is the API ready?
- Are `worker`, `callback-worker`, and `ops-worker` alive?
- Is execution backlog separated from callback backlog?
- Are managed cadence tasks fresh?
- Is provider health fresh, and which provider is degraded?
- Is OTLP tracing wired to the collector endpoint?
- Are addon overview and provider evidence coming from `projection`, or if not, why is `live_fallback` happening?
- Has one real signed runtime request succeeded against the production provider configuration?
