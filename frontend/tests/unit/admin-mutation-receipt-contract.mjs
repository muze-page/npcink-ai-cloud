import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { fromFrontendRoot } from './_paths.mjs';

const receiptSource = readFileSync(fromFrontendRoot('src/components/admin/AdminMutationReceipt.tsx'), 'utf8');
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
