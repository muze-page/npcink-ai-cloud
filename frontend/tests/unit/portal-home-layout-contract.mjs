import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const portalHomePath = resolve(process.cwd(), 'src/app/portal/page.tsx');
const source = readFileSync(portalHomePath, 'utf8');
const sitesWorkspaceSource = readFileSync(
  resolve(process.cwd(), 'src/components/portal/PortalSitesWorkspace.tsx'),
  'utf8'
);

assert.match(
  source,
  /operationSummaryItems\s*=\s*\[/,
  'portal home must build a compact operation summary before rendering'
);

assert.match(
  source,
  /<PortalMetricStrip items=\{operationSummaryItems\}/,
  'portal home must render the account operation summary as a compact metric strip'
);
assert.match(
  source,
  /portalClient\s*\.\s*getAccountEntitlements[\s\S]*accountEntitlements\?\.quota_summary\?\.credit\?\.remaining/,
  'portal home must load account-level entitlement data for remaining package points'
);
assert.match(
  source,
  /portalClient\s*\.\s*listSupportRequests[\s\S]*openTicketCount/,
  'portal home must include account-level open ticket state in the overview'
);
assert.match(
  source,
  /account_status_ok_desc[\s\S]*account_status_issue_desc/,
  'portal home status copy must describe the account, not only the selected site'
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

assert.match(
  source,
  /<PortalSitesWorkspace siteSummaries=\{siteSummaryCache\} \/>/,
  'portal home must pass normalized site summaries into the merged site workspace'
);
assert.match(
  sitesWorkspaceSource,
  /siteSummaries\[site\.site_id\]\?\.customer_status\?\.needs_attention/,
  'portal home site status must include monitoring-derived customer status'
);
const siteRegisterIndex = sitesWorkspaceSource.indexOf('portal.site_register');
assert.ok(siteRegisterIndex >= 0, 'merged site workspace must render a connected-site register section');
const siteRegisterSource = sitesWorkspaceSource.slice(siteRegisterIndex);
assert.doesNotMatch(
  siteRegisterSource,
  /package_card_label|sitePackageDisplay|resolveSitePackageDisplay|hasCachedSiteCoverage/,
  'portal home site register must not show account package as a per-site field'
);

assert.doesNotMatch(
  source.slice(source.indexOf('data-portal-home="operation-overview"'), source.indexOf('<PortalSitesWorkspace')),
  /href="\/portal\/sites"|href="\/portal\/billing"/,
  'portal home summary cards must stay informational instead of duplicating primary navigation'
);

const overviewIndex = source.indexOf('data-portal-home="operation-overview"');
const summaryIndex = source.indexOf('<PortalMetricStrip items={operationSummaryItems}');
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
