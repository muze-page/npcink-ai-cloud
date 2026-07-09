# Runtime Stability Observation - 2026-07-09

Status: initial observation baseline.
Scope: Cloud runtime/detail/service evidence only.
Timestamp: 2026-07-09T06:07:22Z.

## Boundary

This observation starts the structured observation period from
`runtime-stability-performance-evidence-v1.md`.

No runtime behavior was changed. No Go or Rust sidecar was introduced. No new
queue, scheduler, workflow engine, admin control surface, or WordPress write
path was added.

Local WordPress approval, preflight, audit, final writes, ability truth,
workflow truth, prompt truth, router truth, MCP truth, and OpenClaw truth remain
outside Cloud.

## Commands

```bash
git status --short --branch
pnpm run check:runtime-stability-plan
pnpm run perf:runtime-hot-path:require-indexes
docker compose -f docker-compose.dev.yml exec -T postgres psql -U npcink -d npcink_ai_cloud -c "select count(*) filter (where status='queued') as queued, count(*) filter (where status='running') as running, count(*) filter (where status='failed') as failed, count(*) filter (where status='canceled') as canceled, count(*) filter (where status='succeeded') as succeeded from run_records;"
docker compose -f docker-compose.dev.yml exec -T postgres psql -U npcink -d npcink_ai_cloud -c "select count(*) filter (where callback_status='pending') as pending, count(*) filter (where callback_status='dispatching') as dispatching, count(*) filter (where callback_status='failed') as failed, count(*) filter (where callback_status='delivered') as delivered, count(*) filter (where callback_status='not_requested') as not_requested from run_records;"
docker compose -f docker-compose.dev.yml exec -T postgres psql -U npcink -d npcink_ai_cloud -c "select provider_id, count(*) as calls, round(avg(latency_ms)) as avg_latency_ms, max(latency_ms) as max_latency_ms, count(*) filter (where error_code is not null and error_code <> '') as errors from provider_call_records group by provider_id order by calls desc, provider_id limit 10;"
docker compose -f docker-compose.dev.yml exec -T postgres psql -U npcink -d npcink_ai_cloud -c "select event_kind, actor_ref, max(created_at) as last_seen_at, count(*) as events from service_audit_events where event_kind='worker.heartbeat' group by event_kind, actor_ref order by actor_ref;"
```

## Results

### Plan Gate

`pnpm run check:runtime-stability-plan` passed:

```text
runtime_stability_evidence_plan: ok
```

### Runtime Hot Path

`pnpm run perf:runtime-hot-path:require-indexes` passed.

The command used the local Docker development stack. PostgreSQL and Redis were
running and healthy.

Required hot-path indexes were present:

- `ix_run_records_status_started_run`
- `ix_run_records_status_processing_started`
- `ix_run_records_callback_due`
- `ix_run_records_callback_dispatching_lease`

Observed planner behavior in this small local dataset:

- `runtime_queue_claim_candidates` used
  `ix_run_records_status_started_run`.
- `runtime_running_stale_diagnostics`,
  `runtime_callback_due_diagnostics`, and
  `runtime_callback_dispatching_recovery` had their expected indexes available,
  but PostgreSQL chose broader status indexes with small empty result sets.
- No missing index was reported by the required-index gate.

This is an observation item, not a code-change trigger. Recheck with a larger
or production-like dataset before changing index strategy.

### Run Status Baseline

```text
queued: 0
running: 0
failed: 34
canceled: 4
succeeded: 232
```

There was no active queue backlog at observation time.

### Callback Baseline

```text
pending: 0
dispatching: 0
failed: 0
delivered: 0
not_requested: 270
```

There was no pending, dispatching, failed, or delivered callback state in the
current local dataset. Existing records are callback `not_requested`.

### Provider Baseline

```text
provider_id           calls  avg_latency_ms  max_latency_ms  errors
openai               161    18041           60000           37
minimax              70     3559            30000           18
zhihu                14     840             1936            0
pexels               5      318             503             0
cloud_batch_runtime  2      15              25              0
deepseek             2      2315            2342            0
pixabay              2      775             869             0
```

Provider latency and error concentration, especially for `openai` and `minimax`,
is the clearest current observation target. This does not by itself justify a
language rewrite, because the signal is provider/network/runtime-adapter
behavior rather than proven Python CPU or memory saturation.

### Worker Heartbeat Baseline

```text
callback_dispatch  last_seen_at=2026-07-09 06:07:36.776436+00  events=2269
ops_cadence        last_seen_at=2026-07-09 06:07:37.441046+00  events=2255
runtime_queue      last_seen_at=2026-07-08 01:32:45.696258+00  events=1511
```

`callback_dispatch` and `ops_cadence` were fresh at observation time.
`runtime_queue` was stale relative to the current observation timestamp. Because
there was no queued backlog, this is a follow-up observation item rather than an
immediate incident.

## Current Decision

Outcome: `keep_current_stack_observe`.

Do not start a Go or Rust rewrite. Continue observing the existing FastAPI,
PostgreSQL, Redis, and worker stack.

## Next Observation Checks

During the 3-7 day observation period, collect:

- one hosted runtime request that succeeds;
- one queue-backed run, if naturally available;
- one provider failure or timeout, if naturally available;
- callback delivery evidence when a request actually needs callback delivery;
- worker heartbeat freshness when `runtime_queue` is expected to be active;
- provider p95 and p99 once enough new samples exist.

Only make code changes if observation shows a specific existing-stack problem,
such as missing indexes on a realistic dataset, stale worker execution during
actual queued work, callback retry failure, provider timeout misconfiguration,
or an incorrect read-only diagnostic classification.
