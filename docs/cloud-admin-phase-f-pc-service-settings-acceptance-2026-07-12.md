# Cloud Admin Phase F — PC Service Settings Acceptance

Date: 2026-07-12

## Scope

This checkpoint covers the desktop service-settings workspace at `/admin/service-settings`. Mobile and tablet refinement remains deferred; the existing responsive compatibility check is retained only as a regression guard.

## Operator workflow

- Portal URL, QQ login, email delivery, and payment remain four independent task groups with one visible form at a time.
- Dirty state is visible in the active category tab and inside the active form, instead of appearing as a detached page-wide banner.
- Validation and failed-save feedback stay inside the configuration group that produced them.
- The rollback action explicitly restores the last saved values; switching groups still requires confirmation when edits exist.
- Save success remains a compact global toast and does not expand the workspace.
- Payment credentials and callback identity are explicitly marked as high-risk, with server notify documented as the payment truth.
- Initial load failure preserves the admin shell and retries only the bounded service-settings read.

## Verification

- `node tests/unit/admin-service-settings-ui-contract.mjs`
- `node tests/unit/admin-service-settings-pc-v2-contract.mjs`
- `pnpm exec eslint src/app/admin/service-settings/page.tsx tests/e2e/admin-service-settings-v2.spec.ts`
- `pnpm run type-check`
- `pnpm exec playwright test tests/e2e/admin-service-settings-v2.spec.ts`

Result: both contracts, lint, and type-check passed; two service-settings interaction tests passed, covering dirty-state locality, navigation protection, validation, failed-save retention, successful save, rollback, payment risk disclosure, and initial failure/retry.

## Boundary check

The page continues to manage Cloud-owned Portal, QQ, SMTP, and Alipay runtime settings only. It does not own WordPress writes, local registries, prompt/router truth, provider routing, production deployment, or final approval/audit truth.
