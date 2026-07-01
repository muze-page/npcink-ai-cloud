# Admin Runtime Surface Cleanup Closeout - 2026-07-01

Status: local closeout summary.

Purpose: summarize the July 1 admin cleanup around AI Resources, runtime
telemetry, hosted model compatibility, Ability Models, and Internal AI Advisor.
This document records local project history. It does not introduce a new API,
new product surface, second WordPress control plane, or runtime registry.

## Boundary

Npcink AI Cloud remains the hosted runtime and service-plane enhancement layer.
It may own runtime execution, provider adapters, usage and entitlement evidence,
health diagnostics, Site Knowledge runtime/detail, artifacts, and read-only
runtime metadata projections.

Cloud must not become:

- a second WordPress control plane;
- a second local ability registry;
- a second workflow registry;
- a prompt, preset, router, MCP, or OpenClaw truth owner;
- final approval, preflight, or audit truth;
- a WordPress write owner.

The cleanup kept all affected surfaces inside Cloud-owned admin diagnostics,
runtime detail, runtime binding, and read-only advisor boundaries.

## Why This Work Happened

The starting question was whether two admin surfaces were still needed:

- `/admin/troubleshooting` contained an `AI 运营` card that linked to supplier
  management.
- `/admin/hosted-models` exposed a standalone Hosted Models page.

The review found that the standalone UI was redundant. Useful lower-level
capability still existed, but it belonged inside existing operator surfaces:

- provider and runtime diagnostics belong in AI Resources;
- hosted runtime telemetry belongs in runtime detail, not a separate model
  governance product area;
- model/runtime binding belongs in Ability Models, bounded to supported runtime
  bindings;
- Internal AI Advisor is useful as a read-only operations diagnostic and AI
  value evaluation tool, but it should not look like a broad AI control panel.

The product direction was therefore: remove independent UI, reuse useful
capability where it already helps operators, and delete or demote misleading
standalone product framing.

## Product Decisions

### Hosted Models is no longer a standalone destination

`/admin/hosted-models` is retained only as a compatibility redirect:

```text
/admin/hosted-models -> /admin/ai-resources?view=diagnostics
```

There should be no default admin navigation entry or troubleshooting card that
markets Hosted Models as a separate operator area.

### Runtime telemetry replaces hosted model governance naming

The old name `hosted-model-governance` was too narrow and implied a standalone
governance product. The evidence actually covers runtime runs, provider call
records, usage meter events, coverage gaps, provider errors, and failed runs.

New surfaces should use:

```text
/internal/service/runtime/diagnostics/runtime-telemetry
/internal/service/admin/runtime-telemetry
/api/admin/runtime-telemetry
```

Compatibility aliases remain:

```text
/internal/service/runtime/diagnostics/hosted-model-governance
/internal/service/admin/hosted-model-governance
```

Admin overview now exposes `runtime_telemetry` as the preferred field while
keeping `hosted_model_governance` as a compatibility alias.

### AI Resources owns runtime diagnostics

AI Resources now reads the live runtime telemetry projection through
`/api/admin/runtime-telemetry`. The page remains a provider and runtime
operations surface, not a model governance console.

The runtime telemetry area is explicitly read-only evidence. It is sourced from:

- `run_records`
- `provider_call_records`
- `usage_meter_events`

It must not expose prompts, result content, provider keys, routing mutation,
ability mutation, or WordPress writes.

### Ability Models stays bounded to runtime binding

The Ability Models page was kept, but the Cloud-native area was tightened:

- the Cloud-native table defaults to all categories instead of opening on a
  single media tab;
- category filtering is a table header/dropdown filter, not a separate tabbed
  product surface;
- internal profile/provider/model details are behind collapsed detail rows;
- plugin audio routes are excluded from the Cloud-native projection and remain
  in plugin ability routing;
- Cloud-native rows do not introduce a fake Cloud ability routing write path.

This preserves the intended split:

- plugin ability routing can configure plugin route profiles;
- Cloud-native projection shows Cloud-owned runtime dependencies and only
  exposes bounded model binding where supported;
- WordPress plugin switches, prompts, approvals, and final writes stay local.

### Internal AI Advisor is an operations diagnostic helper

`/admin/ai-advisor` was not removed because its lower-level capability is useful:

- compare deterministic rule output with AI output;
- prove whether AI participated, was cached, or fell back to rules;
- inspect redacted operations evidence sent to the advisor;
- track cache, token, cost, review, and value metrics;
- confirm or mark AI output after review.

The UI was reframed from an English-heavy experiment panel into a Chinese
operations surface:

- page title: `运营诊断助手`;
- default action: run a read-only operations diagnosis;
- provider/model/force-refresh/DeepSeek comparison moved under
  `高级评估参数`;
- boundary copy states the parameters are only for internal evaluation and do
  not change routing, packages, WordPress content, or customer state.

The advisor remains read-only. It does not write WordPress, mutate commercial
state, adopt routing profiles, send customer messages, or approve anything.

## Implemented Shape

Backend runtime service:

- `RuntimeService.get_runtime_telemetry_diagnostics(...)`
- `RuntimeService.get_hosted_model_governance_diagnostics(...)` remains as a
  compatibility wrapper.

Internal routes:

- `GET /internal/service/admin/runtime-telemetry`
- `GET /internal/service/runtime/diagnostics/runtime-telemetry`
- legacy hosted-model-governance aliases remain.

Admin overview:

- preferred field: `runtime_telemetry`
- compatibility field: `hosted_model_governance`

Frontend surfaces:

- `/admin/hosted-models` redirects to AI Resources diagnostics;
- `/admin/ai-resources` fetches `/api/admin/runtime-telemetry`;
- `/admin` overview uses `runtimeTelemetry` naming and runtime telemetry copy;
- `/admin/ability-models` shows Cloud-native ability categories as a table
  filter and keeps plugin audio route profiles out of Cloud-native projection;
- `/admin/ai-advisor` is localized and positioned as an operations diagnostic
  helper.

Docs:

- `docs/cloud-billing-entitlement-v1.md` now documents runtime telemetry as the
  preferred diagnostics endpoint and notes the old hosted-model-governance path
  as a compatibility alias.

## Files Touched

Runtime/API:

- `app/api/routes/service.py`
- `app/domain/runtime/service.py`
- `app/domain/provider_resources.py`

Docs:

- `docs/cloud-billing-entitlement-v1.md`
- `docs/admin-runtime-surface-cleanup-closeout-2026-07-01.md`

Frontend:

- `frontend/src/app/admin/hosted-models/page.tsx`
- `frontend/src/app/admin/ai-resources/page.tsx`
- `frontend/src/app/admin/page.tsx`
- `frontend/src/app/admin/ability-models/page.tsx`
- `frontend/src/app/admin/ai-advisor/page.tsx`
- `frontend/src/lib/admin-operator-signals.ts`
- `frontend/src/lib/i18n.ts`

Tests:

- `frontend/tests/e2e/admin-operator-path.spec.ts`
- `frontend/tests/e2e/helpers/admin-operator-fixture.ts`
- `frontend/tests/unit/admin-ai-resources-contract.mjs`
- `frontend/tests/vitest/admin-operator-signals.test.ts`
- `tests/api/test_service_routes.py`

## Verification

The closeout passed these checks:

```bash
pnpm --dir frontend exec tsc --noEmit --pretty false
node frontend/tests/unit/admin-ai-resources-contract.mjs
pnpm --dir frontend exec vitest run tests/vitest/admin-operator-signals.test.ts
pnpm run check:anti-drift
pnpm run check:fast
.venv/bin/python -m pytest \
  tests/api/test_service_routes.py::test_admin_ability_model_runtime_projection_is_bounded_and_feature_backed \
  tests/api/test_service_routes.py::test_runtime_telemetry_diagnostics_summarizes_runtime_families \
  tests/api/test_service_routes.py::test_service_routes_expose_ops_cadence_summary \
  -q
git diff --check
```

Observed results:

- frontend type-check passed;
- AI Resources contract passed;
- admin operator signals Vitest passed;
- anti-drift passed;
- `check:fast` passed:
  - contract: 51 passed, 2 skipped;
  - domain: 127 passed, 3 skipped;
- targeted service route tests passed: 3 passed, 1 warning;
- diff whitespace check passed.

## Follow-Up Notes

No known red validation remains from this cleanup.

Future agents should preserve these rules:

- prefer `runtime_telemetry` and `runtime-telemetry` for new code;
- keep hosted-model-governance only as compatibility language;
- do not re-add a standalone Hosted Models navigation/product surface;
- do not turn AI Advisor into a control panel;
- keep provider/model/AI comparison controls behind advanced/internal UI;
- keep Cloud-native Ability Models as runtime projection and bounded binding,
  not a second ability registry;
- keep WordPress writes, plugin switches, prompts, approvals, and final audit in
  the local WordPress/Core path.
