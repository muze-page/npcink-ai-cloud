import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fromFrontendRoot } from './_paths.mjs';

const read = (path) => readFileSync(fromFrontendRoot(path), 'utf8');
const billingSource = read('src/app/portal/billing/page.tsx');
const dialogSource = read('src/components/portal/PortalCreditPackDialog.tsx');
const clientSource = read('src/lib/portal-client.ts');

assert.match(
  billingSource,
  /<PortalCreditPackDialog[\s\S]*packs=\{availableCreditPacks\}/,
  'Portal billing must pass the effective service catalog to the credit-pack purchase dialog'
);
assert.match(
  clientSource,
  /interface PortalCreditPack[\s\S]*validity_days: number/,
  'Portal credit-pack types must preserve the service catalog validity truth'
);
assert.match(
  dialogSource,
  /portal\.usage\.credit_pack_validity_days/,
  'Portal must disclose each pack validity before the customer confirms payment'
);
assert.match(
  dialogSource,
  /formatValidityLabel\(t, pack\.validity_days\)/,
  'Portal must derive the disclosed validity from each effective catalog item'
);
assert.doesNotMatch(
  dialogSource,
  /credit_packs_period_badge|One-year validity|一年有效/,
  'Portal must not replace configurable pack validity with a fixed one-year label'
);

console.log('portal_credit_pack_purchase_contract: ok');
