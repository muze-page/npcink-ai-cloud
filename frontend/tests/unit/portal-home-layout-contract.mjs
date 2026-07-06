import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const portalHomePath = resolve(process.cwd(), 'src/app/portal/page.tsx');
const source = readFileSync(portalHomePath, 'utf8');

assert.match(
  source,
  /operationSummaryItems\s*=\s*\[/,
  'portal home must build a compact operation summary before rendering'
);

assert.match(
  source,
  /<BackofficeMetricStrip items=\{operationSummaryItems\}/,
  'portal home must render the current site summary as a compact metric strip'
);

assert.match(
  source,
  /data-portal-home="operation-overview"/,
  'portal home must expose a single operation overview surface'
);

assert.match(
  source,
  /shouldShowFollowUpSection/,
  'portal home must only render follow-up sections when there is something to handle'
);
assert.match(
  source,
  /operationFocusItems\.length > 0 \? \(/,
  'portal home must keep current focus conditional instead of showing normal-state confirmation cards'
);
assert.doesNotMatch(
  source,
  /site_status_card_label[\s\S]*package_card_label|package_card_label[\s\S]*site_status_card_label/,
  'portal home must not repeat site and package cards after the primary service summary'
);

assert.match(
  source,
  /data-portal-home="setup-checklist"/,
  'portal home may keep onboarding only as a secondary setup checklist'
);
assert.doesNotMatch(
  source,
  /data-portal-home="no-action-summary"/,
  'portal home must hide no-action summary cards when everything is normal'
);
assert.doesNotMatch(
  source,
  /data-portal-home="quick-links"|portal\.home\.next_action_label[\s\S]*\/portal\/sites\/\$\{selectedSite\.site_id\}|portal\.home\.usage_action[\s\S]*\/portal\/usage\?site=\$\{selectedSite\.site_id\}/,
  'portal home must not repeat global navigation as local quick links'
);

const siteRegisterIndex = source.indexOf('portal.site_register');
assert.ok(siteRegisterIndex >= 0, 'portal home must render a connected-site register section');
const siteRegisterSource = source.slice(siteRegisterIndex);
assert.doesNotMatch(
  siteRegisterSource,
  /package_card_label|sitePackageDisplay|resolveSitePackageDisplay|hasCachedSiteCoverage/,
  'portal home site register must not show account package as a per-site field'
);

assert.doesNotMatch(
  source.slice(source.indexOf('data-portal-home="operation-overview"'), source.indexOf('portal.site_register')),
  /href="\/portal\/sites"|href="\/portal\/billing"/,
  'portal home summary cards must stay informational instead of duplicating primary navigation'
);

const overviewIndex = source.indexOf('data-portal-home="operation-overview"');
const summaryIndex = source.indexOf('<BackofficeMetricStrip items={operationSummaryItems}');
const focusIndex = source.indexOf('data-portal-home="current-focus"');
const checklistIndex = source.indexOf('data-portal-home="setup-checklist"');

assert.ok(overviewIndex >= 0, 'operation overview marker must exist');
assert.ok(summaryIndex > overviewIndex, 'metric summary must render inside the operation overview');
assert.ok(focusIndex > summaryIndex, 'conditional current focus must follow the metric summary');
assert.ok(checklistIndex > focusIndex, 'setup checklist must stay in the conditional follow-up area');

assert.doesNotMatch(
  source,
  /shouldShowStatusPanel|currentRiskLevel|getHomeRiskLevel/,
  'portal home must not keep the old separate risk panel path after layout consolidation'
);

console.log('portal_home_layout_contract: ok');
