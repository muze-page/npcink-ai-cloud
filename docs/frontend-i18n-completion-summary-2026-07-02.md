# Frontend i18n Completion Summary - 2026-07-02

## Status

Completed and locally verified.

## Scope

This note summarizes the frontend i18n cleanup completed across the bounded
Cloud Admin and Portal surfaces. The work stayed inside the hosted runtime
service UI and did not change Cloud runtime contracts, WordPress write
authority, approval flow, prompt/router truth, ability/workflow truth, or
service-plane permissions.

Covered surfaces:

- Admin shell, home, account and site detail, plans, subscriptions, coverage,
  portal users, service settings, ability model grouping, and internal AI
  advisor.
- Portal home, login, site detail, monitoring, media observability, vector
  observability, account, registration, usage, billing, audit, navigation, and
  site inspector surfaces.
- Root service status page.
- Shared visible empty-state fallback for item labels.

## What Changed

- Added bilingual English and Simplified Chinese translation entries for the
  Admin and Portal pages above.
- Converted visible page copy, empty states, badges, notices, button labels,
  table labels, modal copy, and status summaries to `t()`-backed strings.
- Expanded `admin-portal-i18n-completeness-contract` so the main Admin and
  Portal surfaces are checked for missing static translation keys.
- Added `admin/ai-advisor` to the contract after converting its disclosure,
  history, comparison, AI participation, value tracking, scenario, agent
  boundary, safety, and signal sections.
- Added stricter cleanup for visible Chinese fallback strings in `app` and
  `components`, while intentionally leaving comments and `zh-CN` dictionary
  content intact.
- Preserved Cloud boundaries: AI advisor remains read-only operator evidence
  and review display; Portal remains a bounded customer workspace; Cloud does
  not become a WordPress control plane.

## Verification

The following frontend gates passed after the cleanup:

```bash
pnpm run test:i18n-contract
pnpm run type-check
pnpm run lint
```

Additional local scans were used to confirm the strict fallback cleanup:

```bash
rg -n "['\"][^'\"]*[\u4e00-\u9fff]|>[^<]*[\u4e00-\u9fff][^<]*<" frontend/src/app frontend/src/components --glob '!**/*.test.*' --glob '!**/*.md'
rg -n '`[^`]*[\u4e00-\u9fff]' frontend/src/app frontend/src/components --glob '!**/*.test.*' --glob '!**/*.md'
rg -n "t\([^\n]*[\u4e00-\u9fff]|aiText\([^\n]*[\u4e00-\u9fff]" frontend/src/app frontend/src/components --glob '!**/*.test.*'
```

At the time of this summary, the contract reported:

```text
admin_portal_i18n_completeness_contract: ok (1638 keys)
```

## Non-Goals

- Do not remove Chinese comments from source files as part of this i18n pass.
- Do not remove or rewrite `zh-CN` translation values in `frontend/src/lib/i18n.ts`.
- Do not introduce a second ability registry, workflow registry, approval
  surface, router truth, prompt truth, or WordPress write owner in Cloud.
- Do not change runtime APIs, provider execution, billing semantics, or Portal
  authorization behavior.

## Follow-Up Guidance

Future Admin or Portal pages should be added to
`frontend/tests/unit/admin-portal-i18n-completeness-contract.mjs` when they
become user-visible surfaces. New visible fallback strings should default to
English in source code and rely on `zh-CN` entries for Chinese display.
