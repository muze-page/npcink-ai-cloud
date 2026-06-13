# Cloud Agent Feedback Quality Gate v1

Status: active internal gate.

This gate keeps the first `think -> act -> observe -> repeat` loop for local
operator feedback comparable across Cloud and Toolbox changes.

## Scope

The gate covers:

- Cloud Agent feedback event acceptance and summary rollups.
- Content Support regression samples for
  `content_support / editor_content_support_sidebar`.
- The read-only Cloud admin quality dashboard boundary.
- The local WordPress truth boundary for approval, preflight, and final writes.

The gate does not cover:

- Prompt or router editing.
- WordPress publishing or object mutation.
- A second approval, workflow, ability, MCP, or OpenClaw control plane.
- Commercial account, subscription, billing, or package surfaces.

## Command

Run from `/Users/muze/gitee/magick-ai-cloud`:

```bash
pnpm run check:agent-feedback-quality
```

The command runs:

- JSON validation for the checked-in Content Support regression fixture.
- `tests/api/test_agent_feedback_routes.py`.
- Targeted Ruff checks for the feedback route, service, and tests.
- Cloud admin TypeScript type-check.
- Targeted ESLint for the feedback dashboard and navigation entries.
- A frontend boundary contract that blocks mutation controls on the dashboard.

## Current Regression Samples

The fixture lives at:

```text
tests/fixtures/agent_feedback/content_support_regression_samples.json
```

Current expected summary:

- `events_total`: `5`
- `accepted_rate`: `0.4`
- `evidence_useful_rate`: `0.4`
- `evidence_weak_rate`: `0.2`
- `wrong_next_step_rate`: `0.2`

These samples are metadata-only. They must not include prompt text, post
content, provider responses, secrets, confirmation tokens, or write authority.

## Boundary

Cloud may summarize quality signals and show read-only detail. WordPress local
remains the control plane for approval, preflight, final writes, and object
mutation.
