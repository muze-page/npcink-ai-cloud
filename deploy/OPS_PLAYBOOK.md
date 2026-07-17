# Cloud Ops Playbook

> Status: active
>
> Updated: 2026-06-29
>
> Scope: standalone `npcink-ai-cloud` production operations, cadence recovery, signed runtime smoke, release-time troubleshooting

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
- signed `GET /v1/catalog/models`
- signed `POST /v1/runtime/execute`
- signed `GET /v1/runs/{run_id}`
- signed `GET /v1/runs/{run_id}/result`
- signed `GET /v1/stats/profiles/{profile_id}`
- signed `GET /v1/usage/summary`

## Environment Entry Points

Cloud has two operator-known public entry points in the current deployment
model:

- local development: `http://127.0.0.1:8010/`
- production: `https://cloud.npc.ink/`

Configuration ownership:

- local compose may use the loopback origin for development and smoke testing.
- production must set `NPCINK_CLOUD_BASE_URL=https://cloud.npc.ink` in
  `.env.deploy` or the deploy secret store.
- production must set
  `NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST=https://cloud.npc.ink` and
  `NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST=cloud.npc.ink`.
- `/admin/service-settings` owns Portal public URL, QQ login, and SMTP sender
  settings. Do not move those service settings back into `.env`.

Loopback origins are a development convenience only. If a production frontend
requires `http://127.0.0.1:8010` or `localhost` as a public URL, treat that as a
release-blocking environment configuration error.

## Signed Runtime Smoke Semantics

The formal release smoke follows the current hosted runtime contract. It does
not call retired `/v1/addon/*` projection surfaces.

Operator interpretation rules:

- `site_id / key_id / secret` identify a real provisioned, active site API key.
- signed `GET /v1/catalog/models` confirms the public catalog read path.
- signed `POST /v1/runtime/execute` confirms the production provider
  configuration can execute a real hosted runtime request.
- signed `GET /v1/runs/{run_id}` and `/result` confirm run lookup and result
  retrieval through the current runtime contract.
- signed `GET /v1/stats/profiles/{profile_id}` and `/v1/usage/summary` confirm
  runtime detail and usage evidence remain readable.
- missing signed runtime credentials are a release-blocking configuration error.

Manual refresh guidance:

- WordPress local refresh actions must remain local cache or service-status
  reads only.
- Release evidence must come from the signed runtime smoke and internal
  observability endpoints, not from retired addon projection endpoints.
- If runtime smoke fails, inspect provider health, site/key lifecycle,
  entitlement, and runtime worker logs before changing WordPress-side controls.

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

## Resource Tuning Baseline

Tune resources through environment variables and service restarts, not by
editing production application code on the server. Server-side changes remain
limited to `.env.deploy` secrets/config and must be backported if they become
durable release requirements.

Primary knobs:

- `NPCINK_CLOUD_API_WORKERS`: gunicorn API worker count. Keep it within the
  release host CPU and memory budget.
- `NPCINK_CLOUD_RUNTIME_WORKER_POLL_SECONDS`: runtime queue polling cadence.
- `NPCINK_CLOUD_RUNTIME_CALLBACK_WORKER_POLL_SECONDS`: callback dispatch polling
  cadence.
- `NPCINK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS`: heartbeat freshness window
  for worker health checks.
- `NPCINK_CLOUD_OPS_CADENCE_POLL_SECONDS`: ops cadence loop frequency.
- `NPCINK_CLOUD_RETENTION_CLEANUP_INTERVAL_SECONDS`: retention cleanup cadence.
- `NPCINK_CLOUD_USAGE_ROLLUP_INTERVAL_SECONDS`: usage rollup cadence.
- `NPCINK_CLOUD_ROUTER_DIAGNOSTICS_INTERVAL_SECONDS`: router diagnostics cadence.
- `NPCINK_CLOUD_LATENCY_PROBE_INTERVAL_SECONDS`: latency probe cadence.
- `NPCINK_CLOUD_ALERT_PROVIDER_DEGRADATION_INTERVAL_SECONDS`: provider
  degradation alert cadence.
- `NPCINK_CLOUD_PROVIDER_HEALTH_SCAN_INTERVAL_SECONDS`: provider health scan
  cadence.
- `NPCINK_CLOUD_ARTIFACT_RECONCILIATION_INTERVAL_SECONDS`: read-only artifact
  inventory reconciliation cadence.
- `NPCINK_CLOUD_ARTIFACT_RECONCILIATION_SAFETY_WINDOW_SECONDS`: minimum object
  age before an unreferenced object is reported as eligible; C2a never deletes it.
- `NPCINK_CLOUD_ARTIFACT_RECONCILIATION_PAGE_SIZE`: bounded store and database
  inventory page size, from 1 through 500.
- `NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED`: destructive orphan cleanup;
  it defaults to `false` and must remain false until P3-B4C3 is accepted.
- `NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_BATCH_SIZE`: per-cadence candidate cap,
  from 1 through 100; each candidate receives its own non-blocking EX fence.

The artifact volume root must remain stable and writable only by the service
owner or trusted operators. Do not replace its mount, shard directories, or
private publication-fence file while API/runtime/ops workers are running.
C2a `orphan_eligible` remains age evidence and never authorizes manual
deletion. Keep C2b automatic cleanup off until PostgreSQL 16 multi-connection
and real named-volume proof is complete. Before any later enablement, verify
service-account ownership and safe modes for root/shards/files, private `0600`
single-link generation marker and lock files, stable mount/root identity, and
that every namespace writer obeys the advisory fence. See
[`docs/media-derivative-operations-runbook-v1.md`](../docs/media-derivative-operations-runbook-v1.md#orphan-cleanup-enablement-gate)
for the full enablement and rollback checklist.

After any resource or cadence change:

1. Restart only the affected services when possible: `api`, `worker`,
   `callback-worker`, or `ops-worker`.
2. Verify `GET /health/operational-ready`.
3. Verify `GET /internal/service/observability/summary` shows fresh heartbeats.
4. Verify `GET /internal/service/ops/cadence` has no unexpected stale tasks.
5. Run one signed runtime smoke when worker or provider cadence changed.
6. Record the changed variables and rollback values in operator notes.

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
5. If runtime smoke fails after cadence recovery, inspect provider health,
   runtime diagnostics, site/key lifecycle, and entitlement evidence before
   changing WordPress-side controls.
6. After recovery, verify `non_fresh_total == 0`.

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
- Has one real signed runtime request succeeded against the production provider configuration?
- Do signed run lookup, result retrieval, stats, and usage evidence remain readable?
