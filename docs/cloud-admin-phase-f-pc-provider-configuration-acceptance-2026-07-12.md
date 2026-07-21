# Cloud Admin Phase F — PC Provider Configuration Acceptance

Date: 2026-07-12

## Scope

This checkpoint covers the desktop provider directory, selected-supplier inspector, and provider configuration dialog under `/admin/ai-resources`. Mobile and tablet refinement remains deferred.

## Operator workflow

- Model and capability suppliers use the same bounded test action from the selected-supplier inspector.
- Successful and failed tests render beside the supplier and action that produced them; the page does not create a large detached success panel.
- Saving a provider closes the dialog only after the automatic masked test succeeds, uses a compact toast, and keeps the audit receipt in the local toolbar.
- Delete remains available only for Cloud-managed connections, requires a second inline confirmation, and explains the possible routing impact before confirmation.
- The provider dialog traps keyboard focus, supports Escape while idle, restores the invoking control, and prevents background scrolling.
- The save-and-test behavior is associated with the dialog for assistive technology.
- Initial provider-directory failure preserves the admin shell and exposes bounded retry.

## Verification

- `node tests/unit/admin-provider-directory-v2-contract.mjs`
- `node tests/unit/admin-provider-config-pc-v2-contract.mjs`
- `node tests/unit/admin-ai-resources-contract.mjs`
- `pnpm run type-check`
- `pnpm exec playwright test tests/e2e/admin-provider-directory-v2.spec.ts`

Result: three contracts and type-check passed; five desktop interaction tests passed, covering directory focus, capability suppliers, inline test/delete feedback, keyboard dialog operation, and save/test receipt placement.

## Boundary check

The UI continues to manage hosted provider connections and masked runtime diagnostics only. It does not own WordPress writes, local ability or workflow registries, final approval, prompt/router truth, or model-routing governance outside the existing bounded surfaces.
