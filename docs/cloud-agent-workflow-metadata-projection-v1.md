# Cloud Agent Workflow Metadata Projection v1

Status: active
Date: 2026-06-09

## Context

Admin and Portal surfaces need to explain which Cloud-side helpers behave like
agents and which runtime chains behave like workflows. The same labels,
boundaries, and stop conditions were starting to appear in page-local constants,
Portal projections, and tests.

Cloud needs one read-only metadata source for these display projections. It must
not become a second ability registry, workflow registry, approval system, or
WordPress write owner.

## Decision

Use `app/domain/agent_workflow_metadata.py` as the Cloud-owned read-only metadata
projection source for Agent and Workflow UI projection.

The preferred product term is metadata projection: a static runtime projection
catalog for display and diagnostics. It is not a workflow registry, execution
registry, approval registry, or WordPress control-plane registry. Callers should
treat it as metadata projection, not as authority for running or approving work.

The projection may describe:

- agent identity, version, handoff owner, allowed actions, forbidden actions,
  stop conditions, execution pattern, and fail-closed behavior
- workflow identity, contract, owner, UI badges, steps, stop conditions, storage
  mode, and write posture

The projection is exposed to internal Admin through:

- `GET /internal/service/admin/agent-workflow-metadata`

Runtime and projection responses may also expose selected metadata projection
fields:

- `agent_handoff`: runtime handoff snapshot attached to the result
- `agent_metadata_projection`: redacted display projection sourced from the
  metadata projection
- `projection_version`: projection version field
- `workflow_metadata`: workflow display projection sourced from the metadata
  projection

## Boundaries

The metadata projection is allowed to be a Cloud display/detail truth. It is not allowed to be a Cloud control-plane truth.

Forbidden:

- no WordPress writes
- no approval or auto-apply state
- no workflow execution engine
- no local ability registry replacement
- no prompt, preset, router, MCP, or OpenClaw truth
- no secrets, provider credentials, raw request bodies, or customer content

Runtime evidence, proposal inputs, cached summaries, artifacts, and audit records
remain in their owning runtime or service modules. The metadata projection only supplies static UI metadata and redacted boundary projection.

## Current Entries

Agents:

- `internal_ops_advisor_agent`
- `site_knowledge_suggestion_agent`

Workflows:

- `external_web_evidence_preflight`
- `media_derivative_artifact_generation`

## Consumer Rules

Admin pages should fetch or receive the backend projection instead of rebuilding
static labels in page-local constants.

Portal projections may expose redacted agent metadata when it helps customers
understand boundaries. Portal must continue to hide provider IDs, model IDs,
cost, cache keys, raw source context, prompts, and internal review mutation
controls.

Tests should assert projection-backed IDs and write posture rather than
duplicating independent copies of the metadata shape.

## Verification

Use these checks for metadata projection drift:

- `.venv/bin/python -m pytest tests/api/test_service_routes.py::test_admin_agent_workflow_metadata_projection_is_read_only`
- `.venv/bin/python -m pytest tests/api/test_service_routes.py::test_internal_ai_advisor_routes_are_internal_and_evidence_backed`
- `pnpm run test:anti-drift`
- `pnpm run check:agent-workflow-metadata`
