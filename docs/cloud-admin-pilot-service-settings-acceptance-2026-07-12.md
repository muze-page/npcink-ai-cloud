# Cloud Admin Service Settings Pilot Acceptance - 2026-07-12

Status: accepted.

Route: `/admin/service-settings`.

Page model: `configuration workspace`.

Fixture inspected: the current local development service settings page plus a
disposable Playwright admin operator fixture.

No live service setting, credential, payment, email, login, customer,
subscription, package, site, key, billing, or WordPress mutation was executed
during browser verification.

## Implemented Structure

- Replaced the four large readiness metric cards with a compact status strip.
- Split the previous Login area into four explicit task groups: Portal URL,
  QQ login, Email, and Payment.
- Rendered only the active configuration form instead of exposing multiple
  unrelated forms at once.
- Added per-group dirty-state tracking against the last saved snapshot.
- Added discard confirmation before switching groups or following an internal
  admin link, plus a browser unload warning for unsaved edits.
- Added client-side validation before save and disabled test actions while the
  active draft is dirty or invalid.
- Preserved the active draft and error context after a failed save.
- Moved transient success feedback to the global Toast layer so form layout no
  longer shifts after an operation.
- Kept validation and request failures inside the active configuration context.
- Prevented the development Strict Mode double-load from issuing duplicate
  settings reads.

## Browser Evidence

### Desktop task flow

- The page exposes four task tabs and one visible form at a time.
- Editing the Portal URL exposes the unsaved state and enables Save.
- Switching to QQ Login while dirty opens a discard confirmation.
- Cancel keeps both the draft value and the selected Portal URL group.
- Discard and switch restores the saved Portal URL before opening QQ Login.
- An invalid Portal URL blocks Save and shows contextual validation.
- A dirty or invalid QQ draft disables the configuration test action.

### Narrow layout

- Viewport: `390 x 844` CSS pixels.
- Exactly one form remains visible.
- Final document width is `390` pixels and no visible element extends beyond
  the viewport.
- The Toast layer stays inset by 16 pixels on narrow screens and uses centered
  positioning only from the wider-screen breakpoint.
- Responsive transitions are allowed to settle before the strict overflow
  measurement; the final layout assertion remains zero-tolerance.

## Request and Failure Evidence

- Before: 2 duplicate `GET /api/admin/service-settings` responses, 5,964
  encoded bytes total in the development baseline.
- After: 1 initial settings read in the instrumented browser fixture.
- A forced `503` save response retains the edited value, dirty state, and
  recovery action.
- A subsequent successful save refreshes the saved snapshot, shows a Toast,
  and returns the active group to a clean state.

## Automated Evidence

- `admin_service_settings_ui_contract`: passed.
- `admin-service-settings-v2.spec.ts`: passed.
- Targeted ESLint: passed.
- TypeScript type-check: passed.
- Full frontend contract suite: passed.
- Full frontend i18n contract suite: passed (`1803` translation keys).
- Repository `check:fast`: passed (`70` contract tests passed, `1` skipped;
  `191` domain tests passed, `3` skipped).

The focused E2E test verifies:

- one initial settings request and one visible form;
- client validation and action disabling;
- dirty-state visibility and group-switch confirmation;
- internal-navigation and browser-unload protection;
- failed-save draft preservation and successful-save reset;
- mobile Toast containment and zero horizontal overflow.

## Boundary Result

The page remains a Cloud service-plane configuration surface for public portal,
QQ OAuth, SMTP email, and Alipay integration settings. It adds no WordPress
write, approval, local ability registry, workflow registry, prompt, router,
MCP, OpenClaw, or second control-plane ownership.
