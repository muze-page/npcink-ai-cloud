import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path) => readFileSync(resolve(path), 'utf8');
const account = read('src/app/portal/account/page.tsx');
const audit = read('src/app/portal/audit/PortalAuditClient.tsx');
const billing = read('src/app/portal/billing/page.tsx');
const globals = read('src/app/globals.css');
const monitoring = read('src/app/portal/monitoring/page.tsx');
const siteRecord = read('src/app/portal/sites/[siteId]/page.tsx');
const support = read('src/app/portal/support/page.tsx');
const usage = read('src/app/portal/usage/page.tsx');

assert.match(account, /href="\/portal\/audit"/);
assert.doesNotMatch(account, /href="\/portal\/login"/);
assert.match(account, /portal\.account\.settings_eyebrow/);
assert.match(audit, /portal\.audit\.records_title/);

assert.match(monitoring, /portal\.monitoring\.recorded_errors/);
assert.match(monitoring, /portal\.monitoring\.recorded_errors_detail/);

assert.match(siteRecord, /href="\/portal\/account"/);
assert.match(siteRecord, /lg:grid-cols-2/);
assert.doesNotMatch(siteRecord, /contactStatusLabel/);

assert.match(globals, /@media \(max-width: 639px\)[\s\S]*\.portal-shell \.input[\s\S]*font-size: 1rem/);
assert.match(billing, /role="tab"[\s\S]*min-h-11/);
assert.match(billing, /resolvePackageStatusDetail/);
assert.match(billing, /portal\.usage\.payment_order_credit_snapshot/);
assert.match(billing, /portal\.usage\.payment_order_purchase_amount/);
assert.match(billing, /<details[\s\S]*portal\.usage\.payment_orders_title[\s\S]*<\/details>/);
assert.match(billing, /open=\{Number\(paymentOrderCounts\.pending \|\| 0\) > 0\}/);

assert.match(support, /<h2[^>]*>[\s\S]*portal\.support_request_list_title[\s\S]*<\/h2>/);
assert.match(usage, /const creditLedgerPageSize = 10/);
assert.doesNotMatch(usage, /setCreditLedger\(bundle\.creditLedger\)/);

console.log('portal_usability_closeout_contract: ok');
