import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path) => readFileSync(resolve(path), 'utf8');
const account = read('src/app/portal/account/page.tsx');
const audit = read('src/app/portal/audit/PortalAuditClient.tsx');
const billing = read('src/app/portal/billing/page.tsx');
const globals = read('src/app/globals.css');
const layout = read('src/app/portal/layout.tsx');
const monitoringRedirectPath = resolve('src/app/portal/monitoring/page.tsx');
const sitesRedirectPath = resolve('src/app/portal/sites/page.tsx');
const siteServiceStatus = read('src/components/portal/PortalSiteServiceStatus.tsx');
const packagePanel = read('src/components/portal/PortalPackageChangePanel.tsx');
const creditPackDialog = read('src/components/portal/PortalCreditPackDialog.tsx');
const paymentOrderHistory = read('src/components/portal/PortalPaymentOrderHistory.tsx');
const scaffold = read('src/components/backoffice/BackofficeScaffold.tsx');
const siteRecord = read('src/app/portal/sites/[siteId]/page.tsx');
const support = read('src/app/portal/support/page.tsx');
const usage = read('src/app/portal/usage/page.tsx');

assert.match(account, /href="\/portal\/audit"/);
assert.doesNotMatch(account, /href="\/portal\/login"/);
assert.match(account, /portal\.account\.settings_eyebrow/);
assert.match(audit, /portal\.audit\.records_title/);

assert.equal(existsSync(monitoringRedirectPath), false);
assert.equal(existsSync(sitesRedirectPath), false);
assert.match(siteServiceStatus, /portal\.monitoring\.recorded_errors/);
assert.match(siteServiceStatus, /portal\.monitoring\.recorded_errors_detail/);

assert.match(siteRecord, /href="\/portal\/account"/);
assert.match(siteRecord, /lg:grid-cols-2/);
assert.doesNotMatch(siteRecord, /contactStatusLabel/);

assert.match(globals, /@media \(max-width: 639px\)[\s\S]*\.portal-shell \.input[\s\S]*font-size: 1rem/);
assert.match(globals, /\.portal-shell \.btn-primary[\s\S]*background: #0066cc[\s\S]*box-shadow: none/);
assert.match(globals, /\.portal-shell \.btn:active:not\(:disabled\)[\s\S]*scale\(0\.98\)/);
assert.match(globals, /\.portal-shell \.portal-commercial-dialog[\s\S]*border-radius: 18px/);
assert.match(layout, /bg-\[#f5f5f7\][\s\S]*max-w-\[1440px\]/);
assert.doesNotMatch(layout, /radial-gradient/);
assert.match(scaffold, /variant === 'portal'[\s\S]*rounded-\[18px\][\s\S]*bg-white[\s\S]*shadow-none/);
assert.match(paymentOrderHistory, /role="tab"[\s\S]*min-h-11/);
assert.match(billing, /resolvePackageStatusDetail/);
assert.ok(
  billing.indexOf('<PortalEntitlementUsage') < billing.indexOf('id="package-options"'),
  'current package rights must appear before commercial actions'
);
assert.match(billing, /activeCommercialDialog === 'package'[\s\S]*\{packageOptions\}/);
assert.match(billing, /<PortalCreditPackDialog[\s\S]*packs=\{availableCreditPacks\}/);
assert.match(billing, /activeCommercialDialog === 'trial'[\s\S]*\{trialOptions\}/);
assert.doesNotMatch(billing, /href="#package-options"/);
assert.match(packagePanel, /role="radiogroup"[\s\S]*aria-checked=\{selected\}[\s\S]*onConfirm/);
assert.match(creditPackDialog, /selectedPackId === pack\.pack_id[\s\S]*onConfirm/);
assert.match(packagePanel, /border-2 bg-white[\s\S]*focus-visible:ring-\[#0071e3\]/);
assert.match(billing, /portal-commercial-dialog max-w-5xl/);
assert.match(paymentOrderHistory, /portal\.usage\.payment_order_credit_snapshot/);
assert.match(paymentOrderHistory, /portal\.usage\.payment_order_purchase_amount/);
assert.match(paymentOrderHistory, /<details[\s\S]*portal\.usage\.payment_orders_title[\s\S]*<\/details>/);
assert.match(paymentOrderHistory, /open=\{Number\(counts\.pending \|\| 0\) > 0\}/);

assert.match(support, /<h2[^>]*>[\s\S]*portal\.support_request_list_title[\s\S]*<\/h2>/);
assert.match(usage, /const creditEventPageSize = 20/);
assert.doesNotMatch(usage, /setCreditLedger\(bundle\.creditLedger\)/);

console.log('portal_usability_closeout_contract: ok');
