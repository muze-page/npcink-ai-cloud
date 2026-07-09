import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const packageDisplayPath = resolve(root, 'src/lib/customer-package-display.ts');
const billingPagePath = resolve(root, 'src/app/portal/billing/page.tsx');
const portalClientPath = resolve(root, 'src/lib/portal-client.ts');
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
const portalClientSource = readFileSync(portalClientPath, 'utf8');
const entitlementComponentPath = resolve(root, 'src/components/portal/PortalEntitlementUsage.tsx');
const entitlementComponentSource = readFileSync(entitlementComponentPath, 'utf8');
const billingMetricStart = billingPageSource.indexOf('<BackofficeMetricStrip');
const billingMetricStrip = billingPageSource.slice(
  billingMetricStart,
  billingPageSource.indexOf('<BackofficeStackCard', billingMetricStart)
);
assert.doesNotMatch(
  billingPageSource,
  /function coerceFiniteNumber|snapshot\.totals|snapshots\.map/,
  'Portal package page must not render raw package snapshot records on the customer surface'
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
  /portal\.billing\.upgrade_action/,
  'Portal package page must own package upgrade entry points'
);
assert.match(
  billingPageSource,
  /portal\.usage\.credit_packs_title/,
  'Portal package page must own credit pack purchase entry points'
);
assert.match(
  billingPageSource,
  /portal\.usage\.payment_orders_title/,
  'Portal package page must own recent payment order visibility'
);
assert.equal(
  (billingPageSource.match(/const paymentOrdersCard =/g) || []).length,
  1,
  'Portal package page must define one reusable payment order card'
);
assert.equal(
  (billingPageSource.match(/\{paymentOrdersCard\}/g) || []).length,
  2,
  'Portal package page must reuse the same payment order card for no-site and site states'
);
assert.match(
  billingPageSource,
  /payment_return[\s\S]*alipay_return_title[\s\S]*handleRefreshPaymentReturn/,
  'Portal package page must show a read-only Alipay return notice with refresh'
);
assert.match(
  billingPageSource,
  /loadAccountPaymentOrders[\s\S]*listAccountPaymentOrders/,
  'Portal package page must load recent payment orders at account scope'
);
assert.match(
  portalClientSource,
  /async listAccountPaymentOrders[\s\S]*\/account\/payment-orders/,
  'Portal client must expose account-level payment order listing'
);
assert.match(
  portalClientSource,
  /getUsageBundle[\s\S]*listAccountPaymentOrders\(\{ limit: 8 \}\)/,
  'Portal usage bundle must use account-level payment orders so Pro checkout orders are visible without a site'
);
assert.doesNotMatch(
  billingPageSource,
  /payment_return[\s\S]*(markPaid|mark_payment|paid_at|subscription_id\s*=)/,
  'Portal package page must not treat browser payment return as payment truth'
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
  entitlementComponentSource,
  /md:grid-cols-2 lg:grid-cols-3/,
  'Shared entitlement summary must show the three primary package rights on one desktop row'
);
assert.match(
  billingPageSource,
  /resolvePaymentOrderTitle[\s\S]*pack_small[\s\S]*pack_medium[\s\S]*pack_large[\s\S]*portal\.usage\.credit_pack_\$\{packKey\}/,
  'Portal package page must localize credit pack order titles instead of rendering raw provider labels'
);
assert.match(
  billingPageSource,
  /resolvePaymentOrderStatusLabel[\s\S]*payment_order_status_waiting_confirmation/,
  'Portal package page must localize payment order status labels'
);
assert.match(
  billingPageSource,
  /shouldShowPaymentOrder[\s\S]*status !== 'canceled'[\s\S]*filter\(shouldShowPaymentOrder\)/,
  'Portal package page must hide canceled or expired payment orders from the customer order list'
);
assert.doesNotMatch(
  billingPageSource,
  /order\.status_detail\?\.label|order\.status_detail\?\.detail/,
  'Portal package page must not render backend payment-order English labels directly'
);
assert.doesNotMatch(
  billingPageSource,
  /portal\.usage\.credit_pack_validity_days/,
  'Portal package page must not repeat per-card credit pack validity when the section already shows one-year validity'
);
assert.doesNotMatch(
  billingPageSource,
  /<details className="overflow-hidden rounded-\[1\.4rem\] border/,
  'Portal package page must not expose package record snapshots on the customer surface'
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
