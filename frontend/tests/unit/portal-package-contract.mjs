import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const packageDisplayPath = resolve(root, 'src/lib/customer-package-display.ts');
const billingPagePath = resolve(root, 'src/app/portal/billing/page.tsx');
const siteRecordPath = resolve(root, 'src/app/portal/sites/[siteId]/page.tsx');

const packageDisplaySource = readFileSync(packageDisplayPath, 'utf8');
assert.match(
  packageDisplaySource,
  /planVersionId\?: string;/,
  'customer package display must accept planVersionId as a fallback input'
);
assert.match(
  packageDisplaySource,
  /inferPlanIdFromPlanVersionId/,
  'customer package display must expose a plan-version fallback resolver'
);
assert.match(
  packageDisplaySource,
  /function normalizePackageKind\(value: unknown\): PackageKind \| undefined/,
  'customer package display must let missing package kind fall through to plan inference'
);
assert.match(
  packageDisplaySource,
  /if \(!normalized\) \{\s*return undefined;\s*\}/,
  'customer package display must not classify a missing package kind as unknown before plan inference'
);

const billingPageSource = readFileSync(billingPagePath, 'utf8');
const entitlementComponentPath = resolve(root, 'src/components/portal/PortalEntitlementUsage.tsx');
const entitlementComponentSource = readFileSync(entitlementComponentPath, 'utf8');
const billingMetricStart = billingPageSource.indexOf('<BackofficeMetricStrip');
const billingMetricStrip = billingPageSource.slice(
  billingMetricStart,
  billingPageSource.indexOf('<BackofficeStackCard', billingMetricStart)
);
assert.match(
  billingPageSource,
  /function coerceFiniteNumber/,
  'Portal package page must guard invalid numeric snapshot totals'
);
assert.match(
  billingPageSource,
  /planVersionId: snapshotPlanVersionId/,
  'Portal package page must use planVersionId fallback when resolving the current package label'
);
assert.doesNotMatch(
  billingPageSource,
  /formalPlanName: selectedSite\.plan_name|selectedSite\.plan_name/,
  'Portal package page must not derive the account package label from the selected site'
);
assert.doesNotMatch(
  billingPageSource,
  /href=\{`\/portal\/sites\/\$\{selectedSiteId\}`\}|portal\.site_record/,
  'Portal package page must not send users to a site record to understand the account package'
);
assert.match(
  billingPageSource,
  /upgrade_action[\s\S]*credit_packs_title[\s\S]*payment_orders_title/,
  'Portal package page must own package upgrades, credit packs, and payment orders'
);
assert.doesNotMatch(
  billingMetricStrip,
  /package_credit_allowance_label|site_allowance_label/,
  'Portal package header must not repeat package rights that are already shown in the rights card'
);
assert.match(
  billingPageSource,
  /<PortalEntitlementUsage[\s\S]*quotaSummary=\{quotaSummary\}/,
  'Portal package page must show current package rights through the shared entitlement summary'
);
assert.match(
  entitlementComponentSource,
  /package_credit_allowance_label[\s\S]*site_allowance_label/,
  'Shared entitlement summary must keep package points and site allowance visible together'
);
assert.match(
  billingPageSource,
  /<details className="overflow-hidden rounded-\[1\.4rem\] border/,
  'Portal package page must keep package records behind an explicit details reveal'
);
assert.doesNotMatch(
  billingPageSource,
  /formatCurrency\(latestSnapshot\.totals\.cost\)/,
  'Portal package page must not format raw snapshot totals without validating the number'
);

const siteRecordSource = readFileSync(siteRecordPath, 'utf8');
assert.doesNotMatch(
  siteRecordSource,
  /label: t\('common\.package'[\s\S]*value: packageLabel|resolveCustomerPackageDisplay/,
  'Site record header must not show account package as a site-owned field'
);
assert.doesNotMatch(
  siteRecordSource,
  /This is the clearest place to confirm the current package, service status, and connected site address\./,
  'Site record body must not repeat package and service status cards after the header summary'
);
