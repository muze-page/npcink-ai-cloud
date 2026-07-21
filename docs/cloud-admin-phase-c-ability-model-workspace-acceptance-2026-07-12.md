# Cloud Admin Phase C — Ability Model Workspace Acceptance

Date: 2026-07-12
Surface: `/admin/ability-models`

## Change envelope

- Focused module: Cloud runtime model routing workspace.
- Intended change: replace the default wide configuration tables with a read-first directory, a focused inspector, and bounded edit dialogs.
- Explicit non-goals: no provider API changes, no new runtime binding contract, no plugin switch or prompt ownership, no WordPress writes, and no second ability/model/workflow registry.
- Public contracts touched: URL query state only (`surface`, `media`, and `focus`). Existing GET/POST endpoints and mutation receipts remain unchanged.
- Rollback: revert the page, its contract updates, translations, and the dedicated E2E specification.

## Accepted operator model

1. The default surface presents shared WordPress plugin runtime routes, not the full model inventory.
2. Operators select a route in the directory and inspect its current model, runtime policy, and consuming scenarios in the adjacent inspector.
3. Candidate models and policy controls appear only after the operator opens the configuration dialog.
4. The advanced Cloud surface is a read-only runtime dependency projection. Only rows explicitly marked configurable expose the bounded model-binding dialog.
5. Surface, category, and focused row are URL-addressable without turning selection into a mutation.

## Boundary acceptance

- Cloud continues to own runtime profile and supported runtime-instance binding.
- Local plugin switches, prompts, approvals, and final WordPress writes remain outside this surface.
- Cloud-native dependency rows remain projections; the page does not define abilities or routers.
- Existing idempotency keys and durable mutation receipts remain in the dialogs.

## Browser acceptance

- Desktop 1280 px: directory and 22 rem inspector render side by side without horizontal overflow.
- Mobile 390 × 844: directory and inspector stack, the document width remains 390 px, and the default surface contains zero form inputs or dialogs.
- WordPress and Cloud surface selection persists in the URL.
- Both configuration dialogs open successfully; no live mutation was submitted during manual acceptance.
- Light mode and the existing theme tokens remain intact.

## Automated gates

- `pnpm --dir frontend type-check`
- `pnpm --dir frontend lint -- src/app/admin/ability-models/page.tsx`
- `pnpm --dir frontend test:contracts` — all frontend contracts passed; i18n completeness covered 1890 keys.
- `pnpm --dir frontend exec playwright test -c playwright.config.ts tests/e2e/admin-ability-models-workspace-v2.spec.ts` — 2 passed.
- `pnpm run check:fast` — 70 contract tests passed, 1 skipped; 192 domain tests passed, 3 skipped.

## Follow-up

Phase C should continue with remaining detail and diagnostic surfaces. Large-file extraction and shared queue/inspector primitives remain Phase D work so this behavior change stays scoped to one module.
