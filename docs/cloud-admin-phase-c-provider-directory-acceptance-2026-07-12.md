# Cloud Admin Phase C Provider Directory Acceptance - 2026-07-12

Status: accepted for the `/admin/ai-resources` supplier workspace.

Route: `/admin/ai-resources`.

Page model: `queue + inspector`.

Evidence sources: the current local Cloud supplier response and disposable
Playwright fixtures. No provider save, connection test, credential submission,
delete, model-binding change, route change, or WordPress mutation was executed
during browser acceptance.

## Baseline Problems

- The three readiness summaries became three full-width stacked cards on a
  narrow screen.
- Model and capability suppliers used fixed-width `760px` and `960px` tables,
  forcing operators to scan a desktop table inside a mobile overflow region.
- Configuration and destructive actions repeated on every row, competing with
  status and readiness scanning.
- Selecting a supplier did not create a stable detail context and could not be
  restored from the URL.
- Supplier type, search, status, category, and current focus were page-local
  state.
- Development Strict Mode could issue duplicate supplier-catalog reads.

## Implemented Structure

- One compact, three-part readiness strip for model suppliers, capability
  suppliers, and attention items.
- Model and capability suppliers now share a responsive queue pattern with no
  fixed-width table.
- The selected supplier opens in a desktop sticky inspector; on narrow screens
  the inspector follows the queue.
- Routine rows show identity, readiness, model/category context, and latest
  test evidence without repeated configuration or deletion buttons.
- Configure, test, reference links, and guarded deletion live in the inspector
  for the selected supplier.
- The toolbar exposes one primary add action for the active supplier type.
- `supplier`, `q`, `status`, `category`, and `focus` are URL-backed.
- Catalog request guards deduplicate initial reads and reject stale
  replacement.

## Truth And Boundary

- Existing provider connections remain the only supplier execution and
  credential truth.
- Existing model-reference, model-binding, runtime-telemetry, and provider-test
  APIs are unchanged.
- The inspector reads Cloud runtime provider detail. It does not become model
  routing truth, prompt/router ownership, approval truth, or a WordPress write
  surface.
- Secrets remain write-only and are not exposed by the directory or inspector.
- Model binding and runtime diagnostics remain separate explicit destinations.

## Browser Evidence

### Current local supplier state

- The live local response rendered six model suppliers and retained their real
  readiness, model-count, test-time, and reference-link evidence.
- The initial read issued one supplier-catalog request under the disposable E2E
  harness.
- Selecting `MQZJ` wrote `focus=openai_env` to the URL; reload restored the
  selected row and inspector.

### Desktop fixture

- Viewport: `1280 x 720` CSS pixels.
- The supplier queue and inspector rendered side by side.
- Three model supplier rows fit in the default work surface without repeated
  row actions.
- No table element or horizontal overflow surface rendered.

### Narrow fixture and live state

- Viewport: `390 x 844` CSS pixels.
- Document width remained exactly `390` CSS pixels.
- The supplier queue began before `700` CSS pixels and entered the initial
  viewport.
- Summary values remained one strip instead of three stacked cards.
- Supplier rows used normal document width; no `760px` or `960px` internal
  table width remained.

## Automated Evidence

- `admin_provider_directory_v2_contract`: passed.
- Existing `admin_ai_resources_contract`: passed after replacing obsolete
  table-layout assertions with queue-and-inspector requirements.
- Full frontend contract suite: passed (`1870` translation keys covered).
- Full frontend i18n contract suite: passed.
- `admin-provider-directory-v2.spec.ts`: passed (`2` tests).
- Combined provider and operator E2E regression: passed (`11` tests).
- Targeted TypeScript and ESLint checks: passed.
- Repository `pnpm run check:fast`: passed (`70` contract tests passed,
  `1` skipped; `192` domain tests passed, `3` skipped).

## Boundary Result

The refactor changes information hierarchy, responsive behavior, selection
state, and action placement only. It adds no provider registry, model registry,
routing registry, credential truth, payment/entitlement ownership, WordPress
control, approval, ability, workflow, prompt, router, MCP, or OpenClaw truth.
