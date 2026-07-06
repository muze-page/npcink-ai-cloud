import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { fromFrontendRoot } from './_paths.mjs';

const pageSource = readFileSync(fromFrontendRoot('src/app/admin/page.tsx'), 'utf8');
const i18nSource = readFileSync(fromFrontendRoot('src/lib/i18n.ts'), 'utf8');
const zhStart = i18nSource.indexOf("'zh-CN': {");

assert.ok(zhStart > 0, 'i18n dictionary must contain a Simplified Chinese section');

const enSource = i18nSource.slice(0, zhStart);
const zhSource = i18nSource.slice(zhStart);

assert.match(
  pageSource,
  /data-admin-support-lookup/,
  'admin overview must expose a bounded support lookup entry'
);

assert.match(
  pageSource,
  /buildAdminLookupHref\('\/admin\/accounts', supportQuery\)/,
  'support lookup must route account searches through the existing customer register'
);

assert.match(
  pageSource,
  /router\.push\(supportLookupAccountHref\)/,
  'support lookup form submit must open customer search so Enter works from the input'
);

assert.match(
  pageSource,
  /buildAdminLookupHref\('\/admin\/portal-users', supportQuery\)/,
  'support lookup must route Portal user searches through the existing user register'
);

assert.match(
  pageSource,
  /href="\/admin\/coverage"[\s\S]*admin\.home_support_lookup_coverage/,
  'support lookup must keep service status as an explicit follow-up surface'
);

assert.match(
  pageSource,
  /href="\/admin\/troubleshooting"[\s\S]*admin\.home_support_lookup_diagnostics/,
  'support lookup must keep diagnostics as an explicit follow-up surface'
);

assert.doesNotMatch(
  pageSource,
  /\/admin\/coverage\?q=/,
  'support lookup must not imply that coverage supports a generic search query'
);

const requiredKeys = [
  'admin.home_support_lookup_eyebrow',
  'admin.home_support_lookup_title',
  'admin.home_support_lookup_desc',
  'admin.home_support_lookup_label',
  'admin.home_support_lookup_placeholder',
  'admin.home_support_lookup_accounts',
  'admin.home_support_lookup_portal_users',
  'admin.home_support_lookup_coverage',
  'admin.home_support_lookup_diagnostics',
];

for (const key of requiredKeys) {
  const pattern = new RegExp(`'${key.replaceAll('.', '\\.')}':`);
  assert.match(enSource, pattern, `${key} must exist in English translations`);
  assert.match(zhSource, pattern, `${key} must exist in Simplified Chinese translations`);
}

console.log('admin_home_support_lookup_contract: ok');
