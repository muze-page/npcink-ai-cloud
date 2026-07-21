import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const sitesSource = readFileSync(resolve(root, 'src/components/portal/PortalSitesWorkspace.tsx'), 'utf8');
const sitesRedirectPath = resolve(root, 'src/app/portal/sites/page.tsx');
const accountSource = readFileSync(resolve(root, 'src/app/portal/account/page.tsx'), 'utf8');
const homeSource = readFileSync(resolve(root, 'src/app/portal/page.tsx'), 'utf8');
const usageSource = readFileSync(resolve(root, 'src/app/portal/usage/page.tsx'), 'utf8');
const billingSource = readFileSync(resolve(root, 'src/app/portal/billing/page.tsx'), 'utf8');
const auditSource = readFileSync(resolve(root, 'src/app/portal/audit/PortalAuditClient.tsx'), 'utf8');
const monitoringPath = resolve(root, 'src/app/portal/monitoring/page.tsx');
const headerSource = readFileSync(resolve(root, 'src/components/portal/PortalWorkspaceHeader.tsx'), 'utf8');
const paginationSource = readFileSync(resolve(root, 'src/components/ui/ListPagination.tsx'), 'utf8');
const loadingSource = readFileSync(resolve(root, 'src/components/portal/PortalPageState.tsx'), 'utf8');
const portalClientSource = readFileSync(resolve(root, 'src/lib/portal-client.ts'), 'utf8');

assert.match(sitesSource, /const visibleSites = getVisiblePortalSites\(sites\)/);
assert.match(sitesSource, /visibleSites\.length/);
assert.match(sitesSource, /htmlFor="portal-service-site-search"[\s\S]*id="portal-service-site-search"/);
assert.equal(existsSync(sitesRedirectPath), false);
assert.equal(existsSync(monitoringPath), false);
assert.match(homeSource, /<PortalSitesWorkspace \/>/);
assert.doesNotMatch(homeSource, /getSiteSummary|getSiteDiagnostics|siteSummaryCache/);
assert.doesNotMatch(sitesSource, /siteSummaries|PortalSiteSummaryRecord/);
assert.match(portalClientSource, /customer_status:[\s\S]*nestedCustomerStatus\.needs_attention/);
assert.doesNotMatch(
  accountSource,
  /PortalMetricStrip|getVisiblePortalSites\(session\.sites\)\.length/,
  'account header must not repeat login, QQ, and site details already shown below'
);
assert.doesNotMatch(homeSource, /role="button"[\s\S]{0,900}href=\{`\/portal\/sites\/\$\{site\.site_id\}`\}/);

assert.match(
  usageSource,
  /const contextSiteId = session\?\.selected_context\?\.site\.site_id \|\| ''/,
  'account usage must require an explicit selected site context before loading'
);
assert.match(usageSource, /creditEventWindow[\s\S]*creditEventFeature/);
assert.doesNotMatch(
  usageSource,
  /creditLedgerSiteId|portal\.usage\.site_filter_label|siteId:\s*credit/,
  'account usage must not restore the retired per-site credit filter'
);
assert.match(
  usageSource,
  /useLayoutEffect\([\s\S]*setUsage\(null\)[\s\S]*setEntitlements\(null\)[\s\S]*setCreditEventBuckets\(null\)[\s\S]*setCreditTrend\(null\)/,
  'usage must clear account projections immediately when selected context changes'
);
assert.match(billingSource, /id="package-options"[\s\S]*setActiveCommercialDialog\('package'\)/);
assert.doesNotMatch(billingSource, /href="#package-options"/);
assert.match(auditSource, /SUCCESSFUL_AUDIT_OUTCOMES[\s\S]*succeeded[\s\S]*completed/);
assert.match(headerSource, /onSiteChange[\s\S]*<select[\s\S]*onSiteChange\(event\.target\.value\)/);

assert.match(paginationSource, /common\.next_page/);
assert.match(loadingSource, /role="status"[\s\S]*motion-safe:animate-pulse/);
assert.doesNotMatch(loadingSource, /⏳/);

console.log('portal_customer_correctness_contract: ok');
