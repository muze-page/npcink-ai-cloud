# Cloud Admin Phase E — PC Operations Advisor Acceptance

Date: 2026-07-12
Primary viewport: 1440 × 1050 desktop
Surface: `/admin/ai-advisor`

## Change envelope

- Focused module: PC Operations Advisor default working surface.
- Intended change: keep the current diagnosis and recommended evidence primary while moving AI-generation telemetry into advanced evaluation parameters.
- Explicit non-goals: no prompt, provider, model, routing, package, WordPress, or customer-state ownership change; no mobile/tablet redesign.
- Public contracts touched: presentation and localization only. Existing Advisor endpoints and review mutation remain unchanged.
- Rollback: revert the page composition, translations, dedicated tests, and this record.

## Accepted PC operator model

1. Select the diagnostic scope and optional site.
2. Run the diagnosis.
3. Read the localized current conclusion and four operational metrics.
4. Follow recommended actions and open the matching evidence.
5. Review evidence sources and references.
6. Expand advanced evaluation parameters only when testing provider/model behavior, cache, tokens, or request cost.
7. Expand AI evaluation details only when comparing deterministic and AI output.

## Functional corrections

- AI participation, cache, tokens, and request cost no longer dominate the default header.
- Known deterministic Advisor headlines and summaries are localized before default display.
- Known evidence-source labels are localized while raw evidence references remain available.
- Initial load failure preserves the Advisor shell and provides a safe retry.
- Chinese action guidance no longer mixes untranslated `provider` and `fallback` terms.

## PC visual acceptance

- 1440 × 1050 real-data view passed browser inspection.
- The title, scope, site filter, and diagnosis action fit in one compact desktop work panel.
- The current diagnosis begins immediately below the control panel.
- Operational metrics and action/evidence columns remain visible without opening AI evaluation details.
- Technical AI-generation metrics remain hidden under the collapsed advanced-parameter disclosure.

## Automated acceptance

- Dedicated Advisor static contract passed.
- Targeted ESLint passed.
- Frontend type-check passed.
- Dedicated PC Advisor E2E passed.

## Next phase

Continue the PC consistency audit with remaining detail routes, starting with site and subscription detail. Prioritize current conclusion, one bounded follow-up action, and evidence disclosure before visual polish.
