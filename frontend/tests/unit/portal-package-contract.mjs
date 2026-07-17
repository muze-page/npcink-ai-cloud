import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const packageDisplayPath = resolve(root, 'src/lib/customer-package-display.ts');
const billingPagePath = resolve(root, 'src/app/portal/billing/page.tsx');
const creditPackDialogPath = resolve(root, 'src/components/portal/PortalCreditPackDialog.tsx');
const packagePanelPath = resolve(root, 'src/components/portal/PortalPackageChangePanel.tsx');
const paymentOrderHistoryPath = resolve(root, 'src/components/portal/PortalPaymentOrderHistory.tsx');
const paymentReturnNoticePath = resolve(root, 'src/components/portal/PortalPaymentReturnNotice.tsx');
const paymentOrdersHookPath = resolve(root, 'src/hooks/usePortalPaymentOrders.ts');
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
const creditPackDialogSource = readFileSync(creditPackDialogPath, 'utf8');
const packagePanelSource = readFileSync(packagePanelPath, 'utf8');
const paymentOrderHistorySource = readFileSync(paymentOrderHistoryPath, 'utf8');
const paymentReturnNoticeSource = readFileSync(paymentReturnNoticePath, 'utf8');
const paymentOrdersHookSource = readFileSync(paymentOrdersHookPath, 'utf8');
const portalClientSource = readFileSync(portalClientPath, 'utf8');
const entitlementComponentPath = resolve(root, 'src/components/portal/PortalEntitlementUsage.tsx');
const entitlementComponentSource = readFileSync(entitlementComponentPath, 'utf8');
const billingMetricStart = billingPageSource.indexOf('<PortalMetricStrip');
const billingMetricStrip = billingPageSource.slice(
  billingMetricStart,
  billingPageSource.indexOf('<PortalCard', billingMetricStart)
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
  packagePanelSource,
  /href=\{`\/portal\/sites\/\$\{selectedSiteId\}`\}|portal\.site_record/,
  'Portal package page must not send users to a site record to understand the account package'
);
assert.match(
  billingPageSource,
  /portal\.billing\.upgrade_action/,
  'Portal package page must own package upgrade entry points'
);
assert.match(
  creditPackDialogSource,
  /portal\.usage\.credit_packs_title/,
  'Portal package page must own credit pack purchase entry points'
);
assert.match(
  paymentOrderHistorySource,
  /portal\.usage\.payment_orders_title/,
  'Portal package page must own recent payment order visibility'
);
assert.match(
  paymentOrderHistorySource,
  /<details[\s\S]*<summary[\s\S]*portal\.usage\.payment_orders_title[\s\S]*role="tablist"[\s\S]*<\/details>/,
  'Portal package page must keep the payment summary visible and fold lower-priority order actions behind disclosure'
);
assert.equal(
  (billingPageSource.match(/const paymentOrdersCard =/g) || []).length,
  1,
  'Portal package page must define one reusable payment order card'
);
assert.equal(
  (billingPageSource.match(/\{paymentOrdersCard\}/g) || []).length,
  1,
  'Portal package page must render the folded payment order card once in the account package view'
);
assert.match(
  paymentReturnNoticeSource,
  /provider === 'alipay'[\s\S]*alipay_return_title[\s\S]*handleRefresh/,
  'Portal package page must show a read-only Alipay return notice with refresh'
);
assert.match(
  paymentReturnNoticeSource,
  /getAccountPaymentOrder[\s\S]*setTimeout[\s\S]*alipay_return_paid_title/,
  'Portal package page must poll the canonical order and render confirmed payment state'
);
assert.match(
  paymentReturnNoticeSource,
  /reconciled[\s\S]*data-payment-return-metric="credited"[\s\S]*data-payment-return-metric="total-available"[\s\S]*data-payment-return-metric="next-expiry"/,
  'Confirmed credit-pack payment notice must show credited amount, total available, and expiry after reconciliation'
);
assert.match(
  paymentReturnNoticeSource,
  /shouldPoll[\s\S]*visible[\s\S]*order/,
  'Payment success notice must remain visible after return query parameters are cleaned'
);
assert.match(
  packagePanelSource,
  /paid_offer_desc[\s\S]*formatPortalCurrency\(plusOffer\.amount\)[\s\S]*formatPortalCurrency\(proOffer\.amount\)/,
  'Portal paid package copy must render live offer prices instead of hard-coded amounts'
);
assert.doesNotMatch(
  billingPageSource,
  /CNY 15 for 30 days|CNY 29 per month/,
  'Portal package implementation must not keep hard-coded paid prices'
);
assert.match(
  paymentOrdersHookSource,
  /const load[\s\S]*listAccountPaymentOrders[\s\S]*statusGroup[\s\S]*PORTAL_PAYMENT_ORDER_PAGE_SIZE/,
  'Portal package page must load payment orders through the dedicated status-group request'
);
assert.match(
  portalClientSource,
  /async listAccountPaymentOrders[\s\S]*\/account\/payment-orders/,
  'Portal client must expose account-level payment order listing'
);
assert.match(
  portalClientSource,
  /async getAccountPaymentOrder[\s\S]*\/account\/payment-orders\/\$\{encodeURIComponent\(orderId\)\}/,
  'Portal client must expose exact payment-order status lookup for return polling'
);
assert.match(
  portalClientSource,
  /available_actions\?: Array<'continue_payment' \| 'cancel'>[\s\S]*async cancelAccountPaymentOrder[\s\S]*\/account\/payment-orders\/\$\{encodeURIComponent\(orderId\)\}\/cancellation/,
  'Portal payment order contract must expose server-owned actions and unified cancellation'
);
const usageBundleSource = portalClientSource.match(
  /async getUsageBundle[\s\S]*?\n  }\n\n  async getAccountCommercialBundle/
)?.[0] || '';
assert.match(
  usageBundleSource,
  /getAccountUsageSummary\(\)[\s\S]*getAccountEntitlements\(\)/,
  'Portal usage bundle must load only the usage and entitlement data consumed by the usage page'
);
assert.doesNotMatch(
  usageBundleSource,
  /getAccountCreditLedger|listAccountCreditPacks|listAccountPaymentOrders/,
  'Portal usage bundle must not issue unconsumed commercial or payment requests'
);

const commercialBundleSource = portalClientSource.match(
  /async getAccountCommercialBundle[\s\S]*?\n  }\n\n  async getAuditBundle/
)?.[0] || '';
assert.match(
  commercialBundleSource,
  /getAccountEntitlements\(\)[\s\S]*listAccountCreditPacks\(\)[\s\S]*listAccountPlanOffers\(\)/,
  'Portal commercial bundle must load the catalog data consumed by the billing workspace'
);
assert.doesNotMatch(
  commercialBundleSource,
  /getAccountCreditLedger|listAccountPaymentOrders/,
  'Portal commercial bundle must not issue unconsumed ledger or payment requests'
);
assert.doesNotMatch(
  paymentReturnNoticeSource,
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
  /package_remaining_label[\s\S]*paid_remaining_label[\s\S]*total_remaining_label/,
  'Shared entitlement summary must distinguish package, paid, and total available credits'
);
assert.match(
  entitlementComponentSource,
  /md:grid-cols-2 lg:grid-cols-3/,
  'Shared entitlement summary must show the three primary package rights on one desktop row'
);
assert.match(
  paymentOrderHistorySource,
  /resolvePaymentOrderTitle[\s\S]*pack_small[\s\S]*pack_medium[\s\S]*pack_large[\s\S]*portal\.usage\.credit_pack_\$\{packKey\}/,
  'Portal package page must localize credit pack order titles instead of rendering raw provider labels'
);
assert.match(
  paymentOrderHistorySource,
  /resolvePaymentOrderStatusLabel[\s\S]*payment_order_status_waiting_confirmation/,
  'Portal package page must localize payment order status labels'
);
assert.match(
  paymentOrderHistorySource,
  /const tabs[\s\S]*payment_orders_tab_all[\s\S]*payment_orders_tab_pending[\s\S]*payment_orders_tab_paid[\s\S]*payment_orders_tab_closed/,
  'Portal package page must separate payment orders with compact status tabs'
);
assert.match(
  billingPageSource,
  /preparePaymentWindow[\s\S]*window\.open\('about:blank', '_blank'\)[\s\S]*paymentWindow\.location\.replace/,
  'Portal package purchases must pre-open a separate payment tab before the async order request completes'
);
assert.match(
  paymentOrderHistorySource,
  /paymentOrderAllowsAction\(order, 'continue_payment'\)[\s\S]*target="_blank"[\s\S]*rel="noopener noreferrer"/,
  'Portal continue-payment actions must keep the billing workspace open'
);
assert.match(
  paymentOrdersHookSource,
  /window\.addEventListener\('focus', refresh\)[\s\S]*visibilitychange/,
  'Portal package page must refresh payment status when the customer returns from the payment tab'
);
assert.match(
  paymentOrderHistorySource,
  /paymentOrderAllowsAction\(order, 'continue_payment'\)[\s\S]*paymentOrderAllowsAction\(order, 'cancel'\)[\s\S]*payment_order_confirm_cancel/,
  'Portal package page must render server-authorized payment actions with cancel confirmation'
);
assert.doesNotMatch(
  paymentOrderHistorySource,
  /<PortalStatusBadge[\s\S]{0,500}<p[^>]*>[\s\S]{0,120}\{resolvePaymentOrderStatusLabel\(order, t\)\}/,
  'Portal package page must not repeat the same payment status below its badge'
);
assert.doesNotMatch(
  paymentOrderHistorySource,
  /order\.status_detail\?\.label|order\.status_detail\?\.detail/,
  'Portal package page must not render backend payment-order English labels directly'
);
assert.match(
  creditPackDialogSource,
  /portal\.usage\.credit_pack_validity_days[\s\S]*formatValidityLabel\(t, pack\.validity_days\)/,
  'Portal package page must disclose each credit pack validity before purchase confirmation'
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
