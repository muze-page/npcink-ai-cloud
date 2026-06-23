# Cloud Local Integration And Rebuild Guidance

Status: active guidance
Date: 2026-05-30

## Purpose

This document records the current Npcink AI Cloud responsibility boundary after
the project split into:

- `magick-ai-abilities`
- `magick-ai-core`
- `magick-ai-adapter`
- `npcink-ai-cloud`

It also records the current recommendation on whether Cloud should be rebuilt
from scratch or evolved from the existing repository.

## Cloud Role

`npcink-ai-cloud` owns the hosted service side. It is responsible for:

- Cloud API contracts;
- hosted runtime execution;
- queue-backed worker execution;
- run status and result retrieval;
- usage, stats, diagnostics, health, quota, and entitlement;
- provider routing and provider-call telemetry;
- Cloud-side analysis generation;
- Cloud service-plane internal operations.

Cloud is not the local WordPress control plane. It must not own:

- WordPress ability definitions or callbacks;
- local ability registry truth;
- local approval/preflight/audit truth;
- OpenClaw connector truth;
- final WordPress writes;
- prompt, preset, MCP, router, or workflow control-plane truth.

## Sibling Project Responsibilities

| Project | Cloud-facing role |
| --- | --- |
| `magick-ai-abilities` | Supplies local WordPress ability definitions, schemas, callbacks, read-only context, and dry-run previews. It does not call Cloud. |
| `magick-ai-core` | Governs proposals, approvals, preflight, scoped app identity, rate limits, and audit. It does not execute Cloud runs. |
| `magick-ai-adapter` | Connects OpenClaw and local WordPress to Cloud. It shapes requests, signs or authenticates transport, proxies status, and preserves correlation ids. It does not own durable run truth. |
| `npcink-ai-cloud` | Executes hosted work, stores hosted run truth, produces Cloud analysis, and exposes stats/diagnostics/entitlement detail. |

Recommended integration:

```text
OpenClaw
  -> magick-ai-adapter
      -> magick-ai-abilities   // local WordPress context and callbacks
      -> magick-ai-core        // governance, approval, audit, preflight
      -> npcink-ai-cloud       // hosted execution, stats, analysis, workers
```

## Cloud API Shape For Adapter

Cloud should expose service APIs that Adapter can call without giving Adapter a
second execution engine.

Allowed Cloud-side surfaces:

- health and readiness;
- signed runtime execution;
- queued run creation;
- run status/result retrieval;
- read-only analysis generation;
- usage and stats summaries;
- entitlement and quota detail;
- diagnostics for operator support.

Cloud response rules:

- Every hosted run must have Cloud-owned run identity and status.
- Every analysis result that implies a WordPress mutation must be returned as a
  reviewable artifact, not as an applied write.
- Write-like recommendations must include enough structure for Adapter/Core to
  create a governed proposal.
- Cloud must preserve correlation fields sent by Adapter, such as
  `proposal_id`, `correlation_id`, `external_thread_id`, and
  `openclaw_thread_id`, when they are present.
- Cloud must not assume OpenClaw talks to Cloud directly; Adapter is the local
  connector.

## Recommended Near-Term Cloud Work

1. Define a small Adapter-facing Cloud analysis contract:
   - request schema;
   - response schema;
   - auth/signing requirements;
   - correlation fields;
   - run lifecycle;
   - local-approval marker for write-like recommendations.

2. Implement the first read-only analysis lane:
   - accepts local WordPress context from Adapter;
   - executes through existing hosted runtime/worker seams;
   - returns `run_id`, `status`, and a read-only report;
   - does not write WordPress.

3. Reuse existing runtime and stats infrastructure:
   - `app/api/routes/runtime.py`;
   - `app/api/routes/runs.py`;
   - `app/api/routes/stats.py`;
   - `app/workers/runtime_queue.py`;
   - usage and diagnostics services.

4. Add contract tests for the boundary:
   - Adapter-origin requests cannot create WordPress writes;
   - write-like recommendations include local approval/proposal handoff data;
   - Cloud run status remains Cloud-owned;
   - Cloud does not expose task-pack or workflow-control-plane APIs.

5. Keep internal service diagnostics separate from customer-facing APIs:
   - internal operator routes stay under internal/service scope;
   - public Adapter-facing routes stay minimal and signed.

## Rebuild Decision

Current recommendation: do not restart the project from scratch now.

Reasons:

- The repository already has real hosted runtime API routes, run status,
  worker execution, stats, usage, entitlement, diagnostics, provider adapters,
  migrations, and focused tests.
- The current code has already gone through a strong-contraction cleanup that
  removed retired orchestration, task-pack, prompt/preset, and thick portal
  surfaces.
- The current technical stack matches the project phase: FastAPI, PostgreSQL,
  Redis, SQLAlchemy, Alembic, workers, and Docker Compose.
- A full rewrite would spend most effort reimplementing already-working
  infrastructure before validating the new Adapter/Core/Abilities split.

## When A Rebuild Becomes Justified

Consider a new project only if at least one of these becomes true and is proven
with concrete failures:

- Existing auth, runtime, queue, or stats contracts cannot be simplified
  without repeated regressions.
- The current schema prevents the Adapter/Core/Abilities split from being
  expressed cleanly.
- Internal alpha smoke cannot be made repeatable after focused fixes.
- New work repeatedly requires deleting more code than it reuses.
- The repository keeps reintroducing retired control-plane surfaces despite
  boundary tests.

If this happens, write an ADR before starting a new repository.

## Acceptable Alternative To Full Rewrite

Prefer a strangler-style evolution:

1. Freeze the public Cloud contracts that Adapter needs.
2. Add new narrow modules for Adapter-facing analysis and runtime calls.
3. Route only the new contract through those modules.
4. Retire old surfaces behind tests when they are no longer used.
5. Keep migrations and operational evidence in this repository until a proven
   replacement can replay or preserve them.

This allows the team to borrow the good parts of the current project without
throwing away working runtime, billing, stats, and diagnostics infrastructure.

## Prompt For Other Agents

Use this prompt when assigning sibling-repo work:

```text
You are not responsible for npcink-ai-cloud. Do not implement hosted runtime,
Cloud workers, usage/stats truth, diagnostics truth, entitlement truth, or
Cloud-side analysis storage.

Your job is to integrate with Cloud through a thin contract:
- Adapter shapes and signs requests, then proxies Cloud status/result.
- Core governs proposals, approval, preflight, and audit.
- Abilities supplies local WordPress ability definitions and context callbacks.

Do not create a second Cloud run truth, second workflow engine, second approval
store, or direct WordPress write path.
```

## Decision Summary

Cloud should evolve from the current repository. Rebuild only after evidence
shows the existing runtime/service foundation blocks the new split. The next
useful work is a narrow Adapter-facing Cloud analysis/runtime contract plus
tests that prevent Cloud from becoming a second WordPress control plane.
