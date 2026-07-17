# Runtime Stability And Performance Evidence v1

Status: active next-stage plan.
Date: 2026-07-09.

## Purpose

Define the next Cloud engineering stage after the current hosted runtime stack
review.

The stage goal is evidence, not replacement:

- keep the current FastAPI, PostgreSQL, Redis, SQLAlchemy, Alembic, worker, and
  Docker Compose stack;
- prove the hosted runtime path with measured hot-path, queue, callback,
  provider, and operator evidence;
- define an explicit decision gate before any Go or Rust sidecar is considered.

This document does not approve a rewrite.

## Boundary

This work belongs to Cloud runtime and operator evidence only.

Allowed:

- runtime hot-path baseline collection;
- queue, callback, provider, and worker pressure evidence;
- read-only runtime detail acceptance checks;
- operator diagnostics and failure cause classification;
- bounded tuning of the existing FastAPI, PostgreSQL, Redis, and worker seams.

Forbidden:

- moving WordPress approval, preflight, audit, or final writes into Cloud;
- adding a Cloud ability registry, workflow registry, prompt editor, router
  control plane, MCP platform, OpenClaw platform, or WordPress control plane;
- introducing Temporal, Cadence, Airflow, Dagster, Celery, RabbitMQ, Kafka,
  NATS, Pulsar, service mesh, or Kubernetes-first deployment as part of this
  stage;
- treating Redis, queues, callbacks, buffers, or projection data as canonical
  truth;
- implementing a Go or Rust sidecar before this evidence stage produces a
  written acceptance record.

## Focused Module

Focused module: Cloud hosted runtime stability and performance evidence.

Primary owners:

- public runtime route behavior;
- runtime worker claim and completion flow;
- callback dispatch;
- provider execution and latency recording;
- usage, entitlement, and runtime diagnostics read models;
- operator-facing read-only diagnosis of failed or slow runs.

Non-owners:

- WordPress writes;
- local approval or proposal truth;
- local ability, workflow, prompt, preset, router, MCP, or OpenClaw truth;
- customer-facing commercial front-office expansion.

## One Week Sprint Shape

### Day 1: Baseline

Capture the current local or staging state without changing runtime behavior.

Required evidence:

- `pnpm run perf:runtime-hot-path:require-indexes`
- `pnpm run perf:production-baseline` when a production-like database URL is
  available and safe to inspect
- worker heartbeat freshness for `runtime_queue`, `callback_dispatch`, and
  `ops_cadence`
- queued, running, stale-running, pending-callback, and callback-failure counts
- provider latency p50, p95, p99, error rate, and timeout rate by provider and
  model profile

Output:

- a dated evidence note under `docs/` or an operator run record that captures
  command, environment, timestamp, and summarized result.

### Day 2-3: Existing Stack Tuning

Tune only existing seams when the baseline shows a problem.

Allowed tuning:

- PostgreSQL indexes and query shape for runtime hot paths;
- worker poll interval, batch size, and claim/reclaim behavior within the
  existing worker pattern;
- provider timeout, retry, and fallback settings inside the current adapter
  contract;
- callback retry, stale lease reclaim, and failure categorization inside the
  current callback worker;
- read-only diagnostic summaries that help operators distinguish auth,
  entitlement, provider, timeout, queue, callback, contract, and policy causes.

Do not add new infrastructure while tuning.

### Day 4: Runtime Detail Acceptance

For one succeeded run, one failed provider run, one queue-backed run, and one
callback failure, confirm that the available detail can answer:

- which runtime owner handled it;
- which local owner initiated it;
- which execution contract fields were enforced;
- which storage mode applied;
- which provider or worker phase failed or slowed down;
- which usage and entitlement decision was applied;
- which callback state exists;
- which local next action owner should act, if any;
- whether the result is suggestion-only, runtime detail, blocked, or ready for
  local review.

The detail surface must remain read-only unless a separate service-plane policy
explicitly approves a bounded operator action.

### Day 5: Decision Record

Close the sprint with one of three outcomes:

1. `keep_current_stack`: no language or infrastructure change is justified.
2. `tune_current_stack_next`: current stack remains correct, but another
   measured tuning pass is needed.
3. `sidecar_candidate`: a single bounded module may enter design review for Go
   or Rust.

## Go Or Rust Sidecar Gate

A sidecar candidate must satisfy every condition below:

- a named module has repeated measured bottlenecks after current-stack tuning;
- the bottleneck is CPU-bound or memory-bound, not provider latency, DB query
  shape, missing index, retry policy, network behavior, or worker sizing;
- p95 or p99 remains outside the target window for the named workload;
- the module can be isolated behind an existing Cloud runtime/detail contract;
- PostgreSQL remains canonical durable truth;
- Redis remains short-lived coordination only;
- FastAPI remains the public runtime API owner;
- the sidecar owns no WordPress write, approval, proposal, prompt, router,
  ability, workflow, MCP, or OpenClaw truth;
- deployment can be added without making Kubernetes, service mesh, or a new
  queue mandatory;
- rollback is a config or routing rollback to the existing Python path.

Preferred language by module type:

- Go: high-concurrency stateless adapters, callback fan-out, HMAC verification
  helpers, lightweight event forwarding, or bounded internal gateway logic.
- Rust: CPU-heavy pure functions such as media processing, compression,
  parsing, local feature extraction, or memory-sensitive transformations.

Rejected by default:

- whole repository rewrite;
- API rewrite;
- worker rewrite as a batch;
- ORM or migration layer replacement;
- frontend rewrite;
- billing or entitlement rewrite;
- any sidecar that becomes a second truth source.

## Required Gates

For this planning artifact:

```bash
pnpm run check:runtime-stability-plan
```

For implementation work created from this plan, choose the narrowest useful gate
from the touched surface:

```bash
pnpm run perf:runtime-hot-path:require-indexes
pnpm run check:fast
pnpm run check:seam
pnpm run check:perimeter
pnpm run lint
pnpm run check:agent-feedback-quality
```

For multi-repo closeout, use the central matrix from
`/Users/muze/gitee/npcink-workflow-toolbox` instead of copying the matrix into
Cloud:

```bash
composer quality:matrix
composer quality:matrix:run
```

## Rollback

If this stage starts pulling Cloud toward a second control plane or a premature
rewrite, stop the work and roll back to the previous accepted boundary:

- delete any unapproved sidecar design;
- remove any new infrastructure proposal from the current phase;
- keep only measured runtime evidence that helps tune the existing stack;
- return write, approval, prompt, router, ability, workflow, MCP, and OpenClaw
  truth to their existing local owners.
