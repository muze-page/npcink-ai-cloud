# Cloud Admin Phase C — Agent Feedback Quality Acceptance

Date: 2026-07-12
Surface: `/admin/agent-feedback`

## Change envelope

- Focused module: read-only Agent feedback quality evaluation.
- Intended change: replace the metric-card hero and always-visible governance panel with a scoped quality workspace, issue queue, and inspector.
- Explicit non-goals: no prompt/router configuration, approval, preflight, publication, WordPress write, feedback mutation, or control-plane ownership change.
- Public contracts touched: URL query state only (`window`, `site`, and `focus`). The existing GET endpoint remains unchanged.
- Rollback: revert the page, translations, dedicated E2E specification, and this acceptance record.

## Accepted operator model

1. Select a 24-hour or seven-day window and optional site scope.
2. Read event, acceptance, weak-evidence, wrong-next-step, and issue-volume summaries.
3. Select a low-quality label from the issue queue.
4. Inspect its count, share of feedback, current scope, and local-governance boundary.
5. Compare runtime/surface scenarios, label mix, sources, and recent buckets.
6. Open the advanced contract disclosure only when approval, preflight, final-write, or control-plane truth is needed.

## Functional corrections

- Window, site, and selected-quality-label state is URL-backed.
- Initial requests time out after eight seconds and expose a scoped retry.
- Refresh failure retains the last successfully loaded feedback snapshot.
- Request sequence guards prevent stale responses from replacing the current scope.
- Low-quality feedback is promoted into a queue and inspector instead of being buried in equal-weight label cards.
- Contract and governance metadata is secondary evidence behind a collapsed disclosure.
- Mobile trend evidence uses two columns before expanding to four, preventing cramped labels.

## Boundary acceptance

- Cloud remains an evaluation and summary layer only.
- Approval, preflight, and final-write truth remain local to WordPress.
- The page does not configure prompts, routers, workflows, abilities, or publication.
- No production mutation action is exposed.

## Browser and automated acceptance

- Desktop, 390 × 844 mobile, dark-theme, and real empty-state layouts passed browser inspection; the original light theme and desktop viewport were restored.
- Populated issue queue, inspector, URL state, stale-snapshot behavior, and mobile width are covered by fixture.
- `node tests/unit/admin-agent-feedback-i18n-contract.mjs` passed.
- Targeted ESLint passed.
- Dedicated E2E against the running local frontend: 2 passed.

## Follow-up

Begin Phase D by extracting only the repeated diagnostic notice and advanced-evidence shell. Keep page-specific scope controls, anomaly semantics, and inspectors local until a second stable repetition proves a safer abstraction.
