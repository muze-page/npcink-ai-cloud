import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { extname, join, resolve } from 'node:path';
import assert from 'node:assert/strict';
import { frontendRoot } from './_paths.mjs';

const root = frontendRoot;
const i18nPath = resolve(root, 'src/lib/i18n.ts');
const monitoringRedirectPath = resolve(root, 'src/app/portal/monitoring/page.tsx');
const sitesRedirectPath = resolve(root, 'src/app/portal/sites/page.tsx');
const source = readFileSync(i18nPath, 'utf8');

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function getLocaleBlock(locale, nextLocale) {
  const startPattern = new RegExp(`^\\s*(?:'${escapeRegExp(locale)}'|${escapeRegExp(locale)}): \\{$`, 'm');
  const startMatch = source.match(startPattern);
  const start = startMatch ? startMatch.index : -1;
  assert.notEqual(start, -1, `missing locale block: ${locale}`);
  const endPattern = nextLocale
    ? new RegExp(`^\\s*(?:'${escapeRegExp(nextLocale)}'|${escapeRegExp(nextLocale)}): \\{$`, 'm')
    : /\n};/m;
  const endMatch = source.slice(start + 1).match(endPattern);
  const end = endMatch && typeof endMatch.index === 'number' ? start + 1 + endMatch.index : -1;
  assert.notEqual(end, -1, `missing locale block end: ${locale}`);
  return source.slice(start, end);
}

function getTranslationValue(block, key) {
  const match = block.match(new RegExp(`'${escapeRegExp(key)}'\\s*:\\s*'((?:\\\\'|[^'])*)'`));
  return match ? match[1] : null;
}

function collectFiles(dir) {
  const results = [];
  for (const entry of readdirSync(dir)) {
    const fullPath = join(dir, entry);
    const stats = statSync(fullPath);
    if (stats.isDirectory()) {
      results.push(...collectFiles(fullPath));
      continue;
    }
    const extension = extname(fullPath);
    if (extension === '.ts' || extension === '.tsx') {
      results.push(fullPath);
    }
  }
  return results;
}

function collectTranslationKeys(filePath) {
  const fileSource = readFileSync(filePath, 'utf8');
  const matches = fileSource.matchAll(/\bt\(\s*['"]([^'"]+)['"]/g);
  return Array.from(matches, (match) => match[1]);
}

const localeBlocks = {
  en: getLocaleBlock('en', 'zh-CN'),
  'zh-CN': getLocaleBlock('zh-CN'),
};

assert.doesNotMatch(
  source,
  /^\s*'zh-TW': \{/m,
  'Traditional Chinese translations are intentionally not part of the bilingual surface'
);

const translationLockedFiles = [
  resolve(root, 'src/app/admin/layout.tsx'),
  resolve(root, 'src/app/admin/page.tsx'),
  resolve(root, 'src/app/admin/accounts/page.tsx'),
  resolve(root, 'src/app/admin/accounts/[accountId]/page.tsx'),
  resolve(root, 'src/app/admin/ai-advisor/page.tsx'),
  resolve(root, 'src/app/admin/portal-users/page.tsx'),
  resolve(root, 'src/app/admin/service-settings/page.tsx'),
  resolve(root, 'src/app/admin/sites/[siteId]/page.tsx'),
  resolve(root, 'src/app/admin/subscriptions/page.tsx'),
  resolve(root, 'src/app/admin/subscriptions/[subscriptionId]/page.tsx'),
  resolve(root, 'src/app/admin/plans/page.tsx'),
  resolve(root, 'src/app/admin/plans/[planId]/page.tsx'),
  resolve(root, 'src/app/admin/credit-packs/page.tsx'),
  resolve(root, 'src/app/admin/coverage/page.tsx'),
  resolve(root, 'src/components/admin/AdminAuditSummaryPanel.tsx'),
  resolve(root, 'src/components/admin/AdminMutationReceipt.tsx'),
  resolve(root, 'src/app/page.tsx'),
  resolve(root, 'src/app/portal/page.tsx'),
  resolve(root, 'src/app/portal/login/page.tsx'),
  resolve(root, 'src/app/portal/sites/[siteId]/page.tsx'),
  resolve(root, 'src/app/portal/audit/PortalAuditClient.tsx'),
  resolve(root, 'src/components/portal/PortalNavbar.tsx'),
  resolve(root, 'src/components/portal/PortalPluginMonitoringPanel.tsx'),
  resolve(root, 'src/components/portal/PortalMediaProcessingPanel.tsx'),
  resolve(root, 'src/components/portal/PortalSiteKnowledgePanel.tsx'),
  resolve(root, 'src/components/portal/PortalSiteInspectorDrawer.tsx'),
  resolve(root, 'src/app/portal/account/page.tsx'),
  resolve(root, 'src/app/portal/register/page.tsx'),
  resolve(root, 'src/app/portal/usage/page.tsx'),
  resolve(root, 'src/app/portal/billing/page.tsx'),
];

assert.equal(existsSync(monitoringRedirectPath), false);
assert.equal(existsSync(sitesRedirectPath), false);

const keys = new Set();
for (const filePath of translationLockedFiles) {
  const stats = statSync(filePath);
  if (stats.isDirectory()) {
    for (const nestedFilePath of collectFiles(filePath)) {
      for (const key of collectTranslationKeys(nestedFilePath)) {
        keys.add(key);
      }
    }
    continue;
  }
  for (const key of collectTranslationKeys(filePath)) {
    keys.add(key);
  }
}

const requiredKeys = Array.from(keys).sort();

for (const [locale, block] of Object.entries(localeBlocks)) {
  for (const key of requiredKeys) {
    assert.ok(getTranslationValue(block, key), `${locale} is missing ${key}`);
  }
}

console.log(`admin_portal_i18n_completeness_contract: ok (${requiredKeys.length} keys)`);
