import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const clientSource = readFileSync(resolve('src/lib/portal-client.ts'), 'utf8');

function interfaceBlock(name) {
  const marker = new RegExp(`export interface ${name}(?: extends [^{]+)? \\{`);
  const match = marker.exec(clientSource);
  const start = match?.index ?? -1;
  assert.ok(start >= 0, `${name} contract block must exist`);
  const blockStart = start + (match?.[0].length || 0);
  const nextInterface = clientSource.indexOf('\nexport interface ', blockStart);
  const nextType = clientSource.indexOf('\nexport type ', blockStart);
  const candidates = [nextInterface, nextType].filter((index) => index > start);
  const end = candidates.length ? Math.min(...candidates) : clientSource.length;
  return clientSource.slice(start, end);
}

const commercialDtos = [
  'PortalPlanOffer',
  'PortalPlanOfferListPayload',
  'PortalPlanTrialPayload',
  'PortalSubscriptionOrder',
  'PortalSubscriptionOrderPayload',
  'PortalPaymentOrder',
  'PortalPaymentOrderListPayload',
  'PortalCreditPack',
  'PortalCreditPackCatalogPayload',
  'PortalCreditPackOrderPayload',
  'PortalCreditLedgerEntry',
  'PortalCreditLedgerPayload',
  'PortalCreditTrendPayload',
  'PortalCreditEventsPayload',
  'PortalCreditEventBucketsPayload',
  'PortalBillingSnapshot',
  'PortalBillingReconciliation',
];
const forbiddenFields = [
  'account_id',
  'principal_id',
  'metadata',
  'claim_id',
  'external_order_no',
  'provider_trade_no',
];

for (const dto of commercialDtos) {
  const block = interfaceBlock(dto);
  for (const field of forbiddenFields) {
    assert.doesNotMatch(
      block,
      new RegExp(`^\\s*${field}\\??:`, 'm'),
      `${dto} must not expose internal commercial field ${field}`
    );
  }
}

assert.doesNotMatch(
  clientSource,
  /export interface PortalCreditPackPaymentOrder|export type PortalPaymentOrder\s*=/,
  'payment orders must have one strict customer DTO instead of a compatibility alias'
);
assert.match(
  interfaceBlock('PortalPlanTrialPayload'),
  /entitlement_snapshot: PortalSiteEntitlementSnapshot \| null;/,
  'trial entitlement snapshots must use the bounded public projection'
);
assert.match(
  interfaceBlock('PortalCreditLedgerPayload'),
  /usage_detail\?: \{[\s\S]*recent_items\?: PortalCreditLedgerEntry\[\];/,
  'credit ledger usage detail must be explicitly modeled as customer-facing data'
);

const siteSummary = interfaceBlock('PortalSiteSummaryRecord');
assert.match(
  siteSummary,
  /entitlement_snapshot\?: PortalSiteEntitlementSnapshot \| null;/,
  'site summaries must reuse the bounded public entitlement snapshot'
);
assert.doesNotMatch(
  siteSummary,
  /^\s*(?:requests_limit|tokens_limit|features)\??:/m,
  'site summaries must not restore legacy entitlement aliases'
);

const auditEvent = interfaceBlock('PortalAuditEvent');
assert.doesNotMatch(
  auditEvent,
  /^\s*(?:message|payload)\??:/m,
  'Portal audit events must not expose raw internal messages or payloads'
);

for (const method of [
  'getAccountPaymentOrder',
  'cancelAccountPaymentOrder',
  'scheduleFreeDowngrade',
]) {
  const start = clientSource.indexOf(`async ${method}`);
  assert.ok(start >= 0, `${method} must exist`);
  const signature = clientSource.slice(start, clientSource.indexOf('{\n', start) + 2);
  assert.doesNotMatch(
    signature,
    /account_id|principal_id|metadata/,
    `${method} must return only its customer DTO`
  );
}

assert.match(
  clientSource,
  /async removeSite\(siteId: string\): Promise<PortalEnvelope<\{ site: Site; revoked_key_ids: string\[\] \}>>/,
  'site removal must retain its bounded public site response'
);

console.log('portal_commercial_dto_contract: ok');
