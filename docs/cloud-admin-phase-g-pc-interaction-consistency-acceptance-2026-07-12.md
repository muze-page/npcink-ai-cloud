# Cloud Admin Phase G — PC Interaction Consistency Acceptance

Date: 2026-07-12

## Scope

This checkpoint covers shared desktop interaction behavior across the Cloud admin: bounded retries, internal confirmation, modal keyboard behavior, background scroll locking, and trigger-focus restoration. Mobile and tablet layout refinement remains deferred.

## Consistency rules

- Customer, site, and subscription detail reads use the shared route skeleton and local diagnostic retry; none reloads the full admin application.
- Internal navigation with dirty service settings uses the shared application confirmation dialog; browser-native confirm, alert, and prompt are absent from admin business surfaces.
- A shared `useDialogKeyboard` hook contains Tab focus, supports Escape, locks background scrolling, and restores the invoking control.
- Quick switcher, ability-model route editor, Cloud runtime binding, capability-supplier chooser, package editor, and email preview use the shared dialog behavior.
- The existing shared Modal and provider-connection dialog satisfy the same keyboard and focus invariants.
- Mutation failures may use `BackofficeDiagnosticNotice`; contracts do not require duplicated hand-written alert markup.

## Verification

- `node tests/unit/modal-keyboard-accessibility-contract.mjs`
- `node tests/unit/admin-usability-foundation-contract.mjs`
- `node tests/unit/admin-service-settings-ui-contract.mjs`
- `node tests/unit/admin-pc-interaction-consistency-contract.mjs`
- `pnpm run type-check`
- Customer, site, and service-settings retry regression: 6 tests passed.
- Quick switcher and custom-dialog keyboard regression: 13 tests passed.
- Source audit found no `window.alert`, `window.confirm`, `window.prompt`, or `window.location.reload` in admin application and admin component surfaces.

One unrelated legacy operator-path smoke assertion about a provider-call telemetry coverage message failed before reaching package editing. Package-editor keyboard behavior was therefore verified through the dedicated `admin-plan-editor-keyboard-v2.spec.ts`, which passed.

## Boundary check

This phase changes presentation and interaction containment only. It does not move Cloud, WordPress, provider-routing, approval, audit, registry, or production-configuration ownership.
