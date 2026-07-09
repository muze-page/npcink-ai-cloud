# Runtime Stack Decision History - 2026-07-09

Status: accepted summary and handoff.
Scope: Cloud runtime/detail/service evidence.

## Summary

The current Cloud stack remains the right default for the next phase:

- FastAPI for public and internal runtime APIs;
- Pydantic settings and typed payload validation;
- PostgreSQL as durable truth for runs, usage, entitlement, billing snapshots,
  audit evidence, and read models;
- Redis only for worker wake-up, short-lived replay/receipt, queue assist, and
  bounded runtime pressure support;
- SQLAlchemy and Alembic for schema and repository evolution;
- Python workers for runtime queue, callback dispatch, ops cadence, provider
  health, usage rollup, and diagnostics summaries;
- Docker Compose for the current local and remote validation loop;
- bounded Next.js/React frontend surfaces for admin and portal detail, not a
  second control plane.

The decision is to keep this stack, enter a structured observation period, and
avoid Go or Rust rewrites unless later evidence proves a narrow CPU-bound or
memory-bound module cannot be fixed inside the existing runtime seams.

## How We Got Here

The review started from the repository startup protocol:

- checked the dirty worktree and branch state;
- read `README.md`;
- read the active Cloud boundary documents;
- read the legacy hosted runtime and technical stack guardrail contracts;
- inspected the real dependency and deployment files;
- inspected the real runtime, worker, migration, and frontend structure.

The repository already matched the documented stack:

- `pyproject.toml` defines Python 3.12 with FastAPI, Uvicorn, SQLAlchemy,
  psycopg, Redis, Alembic, OpenTelemetry, pytest, Ruff, and mypy.
- `docker-compose.dev.yml` defines PostgreSQL, Redis, API, runtime worker,
  callback worker, ops worker, frontend, and Nginx proxy.
- `frontend/package.json` defines Next.js, React, TypeScript, Tailwind,
  Playwright, Vitest, and ESLint.
- `app/workers/*` already owns runtime queue, callback dispatch, ops cadence,
  provider health, usage rollup, and diagnostics cadence paths.
- `scripts/runtime_hot_path_explain.py` already gives a runtime hot-path
  evidence gate for queue, callback, and provider metrics queries.

The important finding was that this is not currently a language-ceiling problem.
The primary engineering problems are boundary discipline, runtime stability,
operator evidence, provider behavior, queue/callback observability, and
measured tuning of the existing stack.

## Boundary Interpretation

Cloud remains the hosted runtime enhancement layer.

Allowed Cloud responsibilities:

- hosted model execution and routing;
- provider adapters and provider-call telemetry;
- usage, billing, entitlement, and audit evidence;
- health, diagnostics, and read-only runtime detail;
- Site Knowledge and artifact runtime/detail;
- static metadata projections for display and diagnostics;
- queue-backed worker execution where `run_records` remains durable truth.

Forbidden drift:

- second WordPress control plane;
- second ability registry;
- second workflow registry;
- prompt, preset, router, MCP, or OpenClaw truth;
- WordPress writes, final approval, preflight, or local audit ownership;
- Redis, callback, queue, or projection buffers becoming canonical truth;
- Temporal, Celery, RabbitMQ, Kafka, NATS, Pulsar, service mesh, or
  Kubernetes-first expansion during this phase.

Cloud frontend surfaces can show bounded service detail. They must not duplicate
local plugin settings, approval, ability/workflow controls, or WordPress write
surfaces.

## Decision

Keep the existing FastAPI, PostgreSQL, Redis, SQLAlchemy, Alembic, Python
worker, Docker Compose, and bounded Next.js stack.

Do not rewrite the API, workers, repository, frontend, billing, entitlement, or
runtime in Go or Rust.

Do not add a new scheduler, workflow engine, queue platform, or infrastructure
layer.

Move into observation:

- collect runtime hot-path evidence;
- observe queue, running, callback, and worker heartbeat health;
- observe provider p50/p95/p99, timeout rate, and error concentration;
- verify runtime detail can explain success, provider failure, queue-backed
  work, callback state, storage mode, entitlement decisions, and local next
  action owner;
- make only small existing-stack fixes when evidence shows a specific problem.

## Evidence Captured

`docs/runtime-stability-performance-evidence-v1.md` defines the next-stage
plan:

- evidence first, replacement later only if proven;
- a one-week sprint shape for baseline, tuning, runtime detail acceptance, and
  decision record;
- an explicit Go/Rust sidecar gate;
- forbidden infrastructure and control-plane drift.

`docs/runtime-stability-observation-2026-07-09.md` captures the initial
observation baseline:

- `pnpm run check:runtime-stability-plan` passed;
- `pnpm run perf:runtime-hot-path:require-indexes` passed;
- PostgreSQL and Redis were healthy in the local Docker stack;
- required hot-path indexes existed;
- local run status showed no queued/running backlog at observation time;
- callback state had no pending, dispatching, failed, or delivered callbacks in
  the local dataset;
- provider latency and error concentration were most visible for `openai` and
  `minimax`;
- `callback_dispatch` and `ops_cadence` heartbeats were fresh, while
  `runtime_queue` heartbeat was stale relative to the observation timestamp and
  should be rechecked when queued work is expected.

The initial evidence supports observation and provider/runtime tuning, not a
language rewrite.

## Go Or Rust Position

Go and Rust are not rejected forever. They are rejected as a default next step.

Consider Go only for a narrow, stateless, high-concurrency module such as:

- callback fan-out;
- HMAC verification helper;
- lightweight event forwarding;
- bounded internal gateway logic.

Consider Rust only for a narrow, CPU-heavy or memory-sensitive pure function
such as:

- media processing;
- compression;
- parsing;
- local feature extraction;
- deterministic transformation with no product truth ownership.

Any candidate must satisfy all of these:

- repeated measured bottleneck after current-stack tuning;
- CPU-bound or memory-bound cause, not provider latency, DB query shape, missing
  index, retry policy, network behavior, or worker sizing;
- p95 or p99 remains outside target for a named workload;
- isolated behind an existing Cloud runtime/detail contract;
- PostgreSQL remains canonical durable truth;
- Redis remains short-lived coordination only;
- FastAPI remains the public runtime API owner;
- no WordPress write, approval, proposal, prompt, router, ability, workflow,
  MCP, or OpenClaw truth moves into the sidecar;
- deployment does not require Kubernetes, service mesh, or a new queue;
- rollback is a config or routing rollback to the existing Python path.

## Development Rules Going Forward

When a future task touches runtime stability or performance:

1. Start by reading this document,
   `docs/runtime-stability-performance-evidence-v1.md`, and the active Cloud
   boundary documents.
2. Run the narrowest evidence gate before proposing a redesign.
3. Treat provider long tail and network behavior separately from Python runtime
   performance.
4. Prefer indexes, query shape, worker parameters, timeout/retry/fallback
   tuning, and diagnostic classification before adding infrastructure.
5. Keep diagnostics read-only unless a service-plane policy explicitly defines
   a bounded operator action.
6. Record new observations as dated docs before making broader architecture
   claims.

## Commit Scope For This Decision

The implementation scope for this decision is documentation and guardrail only:

- `docs/runtime-stack-decision-history-2026-07-09.md`;
- `docs/runtime-stability-performance-evidence-v1.md`;
- `docs/runtime-stability-observation-2026-07-09.md`;
- `scripts/check-runtime-stability-evidence-plan.js`;
- `package.json` script entry for `check:runtime-stability-plan`.

No runtime behavior, database schema, API contract, worker behavior, admin UI,
portal UI, or WordPress integration behavior is changed by this decision.
