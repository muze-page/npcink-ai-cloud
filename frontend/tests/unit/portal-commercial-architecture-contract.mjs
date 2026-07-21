import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const billingSource = readFileSync(resolve('src/app/portal/billing/page.tsx'), 'utf8');

for (const boundary of [
  'usePortalCommercialCatalog',
  'usePortalPaymentOrders',
  'PortalPackageChangePanel',
  'PortalCreditPackDialog',
  'PortalTrialEligibilityPanel',
  'PortalPaymentOrderHistory',
]) {
  assert.match(billingSource, new RegExp(boundary));
}

assert.doesNotMatch(billingSource, /portalClient\.listAccountPaymentOrders/);
assert.doesNotMatch(billingSource, /portalClient\.cancelAccountPaymentOrder/);
assert.doesNotMatch(billingSource, /function resolvePaymentOrderTitle/);
assert.doesNotMatch(billingSource, /const packageChoices/);

console.log('portal_commercial_architecture_contract: ok');
