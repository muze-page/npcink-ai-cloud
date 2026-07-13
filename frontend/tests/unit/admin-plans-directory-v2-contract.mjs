import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fromFrontendRoot } from './_paths.mjs';

const source = readFileSync(fromFrontendRoot('src/app/admin/plans/page.tsx'), 'utf8');

assert.match(source, /BackofficeLayer/, 'package catalog must use the compact operating header');
assert.match(source, /BackofficeSummaryStrip/, 'package catalog must expose a compact status summary');
assert.doesNotMatch(source, /BackofficePrimaryPanel|BackofficeMetricStrip/, 'package catalog must not restore the old hero metric surface');

for (const parameter of ['q', 'state', 'sort', 'focus']) {
  assert.match(source, new RegExp(`searchParams\\.get\\('${parameter}'\\)`), `${parameter} must be URL-backed`);
}

assert.match(source, /activeRequestRef[\s\S]*requestSequenceRef[\s\S]*hasLoadedRef/, 'catalog reads must dedupe and reject stale responses');
assert.match(source, /admin\.plans\.retained_notice/, 'failed refreshes must retain and label the last successful catalog');
assert.match(source, /data-ui="plan-catalog-item"/, 'standard packages must render as a responsive operating list');
assert.match(source, /id="plan-catalog-inspector"/, 'one package inspector must contain package context and follow-up actions');
assert.match(source, /admin\.plans\.open_subscriptions_action/, 'the inspector must open the existing subscription queue');
assert.match(source, /admin\.plans\.open_advanced_setup/, 'missing packages must open the bounded advanced-maintenance path');

assert.match(source, /id="package-maintenance"/, 'package initialization and exceptional creation must remain in advanced maintenance');
assert.match(source, /toast\.success/, 'transient plan mutation success must use global toast feedback');
assert.match(source, /plans and published plan versions as Cloud commercial truth/, 'the inspector must state the package truth boundary');

console.log('admin_plans_directory_v2_contract: ok');
