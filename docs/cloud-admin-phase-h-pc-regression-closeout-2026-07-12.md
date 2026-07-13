# Cloud Admin Phase H: PC regression closeout

Date: 2026-07-12

## Scope

- Surface: `/admin` desktop operator workspace.
- Viewport priority: PC only. Mobile and tablet layout work is deferred.
- Boundary: Cloud remains a hosted runtime and operator-evidence surface. This phase does not add WordPress writes, a second registry, or approval truth.

## Closeout corrections

- Aligned the legacy operator-path assertions with the new read-first hierarchy: one current conclusion and one next action remain visible; detailed subscription, site, audit, and runtime evidence stays inside explicit disclosures.
- Removed asynchronous URL-write races from the service-risk queue so status, search, reason, sort, and inspector focus survive rapid PC interaction and reload.
- Made ticket-search submission read the submitted form value instead of a potentially stale React closure, while keeping URL state and retained-result failure feedback stable.
- Kept failure recovery bounded to the current route. No admin source uses native `alert`, `confirm`, `prompt`, or full-page reload for ordinary recovery.
- Kept dialog keyboard behavior consistent across the quick switcher, provider and capability dialogs, package editor, ability-model dialogs, email preview, and shared modal surfaces.

## Verification evidence

- Admin static contracts: 45 passed. The only remaining failure in the broad `admin-credit-packs-contract.mjs` is a Portal billing section assertion and is outside this `/admin` PC phase.
- Admin Playwright matrix: all 52 scenarios were exercised. The final combined run passed 51 scenarios; the one isolated queue-header timing assertion passed immediately when rerun alone. The two real URL/form races discovered by the matrix were corrected and passed focused stress runs (service queue 3/3; ticket queue 5/5).
- `pnpm run type-check`: passed.
- `pnpm run test:i18n-contract`: passed, including 1,784 admin/Portal keys.
- `pnpm run lint`: passed with zero warnings.
- Root `pnpm run check:fast`: passed (`70 passed, 1 skipped` contract; `194 passed, 3 skipped` domain).

## Deferred work

- Mobile and tablet layout acceptance.
- Portal billing contract regression owned by the concurrent Portal workstream.
- If the combined Playwright matrix continues to expose isolated cold-compile timing, stabilize the test server lifecycle separately; do not weaken product assertions.

## Acceptance conclusion

The PC admin restructuring is functionally closed for this phase. Its navigation, task hierarchy, failure recovery, dialogs, and URL-backed queue state are suitable for operator acceptance. The next product phase should be observation-led refinement from real PC operator sessions, not another broad visual rewrite.
