import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const root = process.cwd();
const source = readFileSync(resolve(root, 'src/app/portal/page.tsx'), 'utf8');
const sitesWorkspaceSource = readFileSync(
  resolve(root, 'src/components/portal/PortalSitesWorkspace.tsx'),
  'utf8'
);

const homeClientCalls = Array.from(
  source.matchAll(/portalClient\s*\.\s*([A-Za-z0-9_]+)\s*\(/g),
  (match) => match[1]
);

assert.deepEqual(
  homeClientCalls,
  ['getAccountEntitlements'],
  'Portal home may make at most one request beyond the shared session request'
);
for (const forbiddenMethod of [
  'getSiteSummary',
  'getSiteDiagnostics',
  'getIdentityProviders',
  'listSupportRequests',
]) {
  assert.ok(
    !source.includes(forbiddenMethod),
    `Portal home must not call ${forbiddenMethod}`
  );
}
assert.doesNotMatch(
  source,
  /Promise\.all(?:Settled)?|siteSummaryCache|PortalSiteInspectorDrawer/,
  'Portal home must not fan out per-site requests or retain a summary drawer cache'
);

assert.match(source, /operationSummaryItems\s*=\s*\[/);
assert.match(source, /<PortalMetricStrip items=\{operationSummaryItems\}/);
assert.match(
  source,
  /accountEntitlements\?\.quota_summary\?\.credit\?\.remaining/,
  'Portal home must use the one account entitlement response for remaining credits'
);
assert.match(source, /data-portal-home="operation-overview"/);
assert.match(source, /shouldShowFollowUpSection/);
assert.match(source, /operationFocusItems\.length > 0 \? \(/);
assert.match(source, /data-portal-home="setup-checklist"/);
assert.doesNotMatch(source, /data-portal-home="no-action-summary"/);

assert.match(
  source,
  /<PortalSitesWorkspace \/>/,
  'Portal home must render the session-backed site workspace without summary props'
);
assert.doesNotMatch(
  sitesWorkspaceSource,
  /siteSummaries|PortalSiteSummaryRecord|getSiteSummary|getSiteDiagnostics/,
  'Portal site list must not depend on detail or diagnostic projections'
);
assert.match(
  sitesWorkspaceSource,
  /portalSiteNeedsAttention\(site\)/,
  'Portal site list must derive scan status from the session site status and URL'
);

const siteRegisterIndex = sitesWorkspaceSource.indexOf('portal.site_register');
assert.ok(siteRegisterIndex >= 0, 'merged site workspace must render a connected-site register');
assert.doesNotMatch(
  sitesWorkspaceSource.slice(siteRegisterIndex),
  /package_card_label|sitePackageDisplay|resolveSitePackageDisplay|hasCachedSiteCoverage/,
  'Portal site register must not show account package as a per-site field'
);

const overviewIndex = source.indexOf('data-portal-home="operation-overview"');
const summaryIndex = source.indexOf('<PortalMetricStrip items={operationSummaryItems}');
const focusIndex = source.indexOf('data-portal-home="current-focus"');
const checklistIndex = source.indexOf('data-portal-home="setup-checklist"');
assert.ok(overviewIndex >= 0);
assert.ok(summaryIndex > overviewIndex);
assert.ok(focusIndex > summaryIndex);
assert.ok(checklistIndex > focusIndex);

console.log('portal_home_layout_contract: ok');
