# Release Readiness Cleanup Closeout 2026-07-07

Status: cleanup baseline ready for review.

## Scope

This closeout records the contraction cleanup before external users depend on
the Cloud API surface.

The cleanup has two parts:

- retired prompt and preset recommendation paths were removed from usage
  service code and tests;
- Agent/Workflow display metadata was collapsed to the metadata projection
  contract only.

## Decisions

Cloud remains the hosted runtime enhancement and service-detail layer. It does
not own prompt, preset, router, ability, workflow, approval, preflight, audit, or
WordPress write truth.

Because this project is still in development and has no dependent users, the
metadata projection API does not keep a registry compatibility layer.

Current contract terms:

- `agent_metadata_projection` is the only redacted Agent display projection
  field on Admin and Portal Advisor responses.
- `projection_version` is the only version field on the Agent/Workflow metadata
  projection endpoint.
- `workflow_metadata` remains the workflow display/detail projection field for
  runtime surfaces that expose workflow posture.

Removed terms must not be reintroduced without an explicit migration reason:

- `agent_registry_metadata`
- `registry_version`
- `compatibility_registry_version`
- `get_agent_workflow_registry`
- `registry_metadata_tokens`

## Verification

Focused gates for this cleanup:

```bash
.venv/bin/python -m pytest tests/api/test_service_routes.py::test_admin_agent_workflow_metadata_projection_is_read_only tests/api/test_service_routes.py::test_internal_ai_advisor_routes_are_internal_and_evidence_backed tests/api/test_portal_routes.py::test_portal_ai_insights_are_manual_cached_and_redacted -q
.venv/bin/ruff check app/domain/agent_workflow_metadata.py app/domain/advisor/service.py app/api/routes/portal.py app/domain/media_derivatives/artifacts.py app/domain/web_search/service.py tests/api/test_service_routes.py tests/api/test_portal_routes.py
pnpm run check:anti-drift
pnpm run test:anti-drift
pnpm run check:agent-workflow-metadata
git diff --check
```

Before merging this baseline, also run:

```bash
pnpm run check:fast
pnpm run check:perimeter
```
