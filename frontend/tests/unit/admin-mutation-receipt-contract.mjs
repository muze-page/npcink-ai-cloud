import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { fromFrontendRoot } from './_paths.mjs';

const receiptSource = readFileSync(fromFrontendRoot('src/components/admin/AdminMutationReceipt.tsx'), 'utf8');
const accountDetailSource = readFileSync(fromFrontendRoot('src/app/admin/accounts/[accountId]/page.tsx'), 'utf8');
const portalUsersSource = readFileSync(fromFrontendRoot('src/app/admin/portal-users/page.tsx'), 'utf8');
const subscriptionDetailSource = readFileSync(fromFrontendRoot('src/app/admin/subscriptions/[subscriptionId]/page.tsx'), 'utf8');
const aiResourcesSource = readFileSync(fromFrontendRoot('src/app/admin/ai-resources/page.tsx'), 'utf8');
const abilityModelsSource = readFileSync(fromFrontendRoot('src/app/admin/ability-models/page.tsx'), 'utf8');
const serviceSettingsSource = readFileSync(fromFrontendRoot('src/app/admin/service-settings/page.tsx'), 'utf8');
const i18nSource = readFileSync(fromFrontendRoot('src/lib/i18n.ts'), 'utf8');
const zhStart = i18nSource.indexOf("'zh-CN': {");

assert.ok(zhStart > 0, 'i18n dictionary must contain a Simplified Chinese section');

const enSource = i18nSource.slice(0, zhStart);
const zhSource = i18nSource.slice(zhStart);

assert.match(
  receiptSource,
  /export function buildAdminMutationReceiptText/,
  'admin mutation receipt must provide a stable copyable text formatter'
);

assert.match(
  receiptSource,
  /navigator\.clipboard\.writeText\(buildAdminMutationReceiptText\(receipt\)\)/,
  'admin mutation receipt must let operators copy the latest operation receipt'
);

assert.match(
  receiptSource,
  /buildAdminAuditTrailHref\(receipt\)/,
  'admin mutation receipt must keep the audit trail follow-up link'
);

assert.doesNotMatch(
  receiptSource,
  />View audit trail</,
  'admin mutation receipt must not hard-code English audit link copy'
);

assert.match(
  accountDetailSource,
  /AdminMutationReceipt[\s\S]*AdminMutationReceiptPayload/,
  'Account detail commercial writes must render the shared admin mutation receipt'
);

assert.match(
  accountDetailSource,
  /setAccountStatusReceipt\(\(payload\.data\?\.receipt \|\| null\) as AdminMutationReceiptPayload \| null\)/,
  'Account status writes must store the backend receipt instead of only showing a toast'
);

assert.match(
  accountDetailSource,
  /setPackageActionReceipt\(\(payload\.data\?\.receipt \|\| null\) as AdminMutationReceiptPayload \| null\)/,
  'Account package, top-up, and credit writes must store the backend receipt instead of only showing a toast'
);

assert.match(
  portalUsersSource,
  /AdminMutationReceipt[\s\S]*AdminMutationReceiptPayload/,
  'Portal user disable writes must render the shared admin mutation receipt'
);

assert.match(
  portalUsersSource,
  /setLastReceipt\(data\.receipt \|\| null\)/,
  'Portal user disable writes must store the backend receipt instead of only showing a toast'
);

assert.match(
  subscriptionDetailSource,
  /AdminMutationReceipt[\s\S]*AdminMutationReceiptPayload/,
  'Subscription billing snapshot rebuild must render the shared admin mutation receipt'
);

assert.match(
  subscriptionDetailSource,
  /setLastReceipt\(data\.receipt \|\| null\)/,
  'Subscription billing snapshot rebuild must store the backend receipt instead of only showing a toast'
);

assert.match(
  aiResourcesSource,
  /AdminMutationReceipt[\s\S]*AdminMutationReceiptPayload/,
  'AI resources provider writes must render the shared admin mutation receipt'
);

assert.match(
  aiResourcesSource,
  /setLastReceipt\(\(payload\.data\?\.receipt \|\| null\) as AdminMutationReceiptPayload \| null\)/,
  'AI resources provider writes must store backend receipts for save, delete, and test operations'
);

assert.match(
  abilityModelsSource,
  /AdminMutationReceipt[\s\S]*AdminMutationReceiptPayload/,
  'Ability-model routing writes must render the shared admin mutation receipt'
);

assert.match(
  abilityModelsSource,
  /setDialogReceipt\(\(payload\.data\?\.receipt \|\| null\) as AdminMutationReceiptPayload \| null\)/,
  'Ability-model routing writes must store backend receipts in the save dialog'
);

for (const [source, label] of [
  [aiResourcesSource, 'AI resources'],
  [abilityModelsSource, 'Ability-model routing'],
  [serviceSettingsSource, 'Service settings'],
]) {
  assert.match(
    source,
    /descriptionDisplay="hint"/,
    `${label} must collect low-frequency top-level descriptions behind an info hint`
  );
}

const requiredKeys = [
  'admin.receipt_latest',
  'admin.receipt_copy',
  'admin.receipt_copied',
  'admin.receipt_copy_failed',
  'admin.receipt_view_audit',
  'admin.receipt_audit_event',
];

for (const key of requiredKeys) {
  const pattern = new RegExp(`'${key.replaceAll('.', '\\.')}':`);
  assert.match(enSource, pattern, `${key} must exist in English translations`);
  assert.match(zhSource, pattern, `${key} must exist in Simplified Chinese translations`);
}

console.log('admin_mutation_receipt_contract: ok');
