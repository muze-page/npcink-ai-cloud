import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const billingSource = readFileSync(resolve('src/app/portal/billing/page.tsx'), 'utf8');
const packagePanelSource = readFileSync(resolve('src/components/portal/PortalPackageChangePanel.tsx'), 'utf8');
const clientSource = readFileSync(resolve('src/lib/portal-client.ts'), 'utf8');
const i18nSource = readFileSync(resolve('src/lib/i18n.ts'), 'utf8');

assert.match(
  clientSource,
  /interface PortalPlanComparisonTier[\s\S]*monthly_points[\s\S]*site_limit[\s\S]*knowledge_article_limit[\s\S]*concurrency_limit[\s\S]*batch_item_limit/
);
assert.match(clientSource, /comparison_tiers\?: PortalPlanComparisonTier\[\]/);
assert.match(clientSource, /comparison_rights\?: Record<PortalPlanComparisonRightKey, PortalPlanComparisonRight>/);

assert.match(billingSource, /const comparisonTiers = planOffers\?\.comparison_tiers \|\| \[\]/);
assert.match(billingSource, /<PortalPackageChangePanel[\s\S]*comparisonTiers=\{comparisonTiers\}/);
assert.match(packagePanelSource, /package_comparison_title[\s\S]*package_only_differences[\s\S]*<table/);
assert.match(
  packagePanelSource,
  /compare_monthly_points[\s\S]*compare_site_limit[\s\S]*compare_knowledge_limit[\s\S]*compare_concurrency_limit[\s\S]*compare_batch_limit/
);
assert.match(packagePanelSource, /showOnlyDifferences[\s\S]*new Set\(comparisonTiers\.map/);
assert.match(packagePanelSource, /formatComparisonRight[\s\S]*tier\.comparison_rights\?\.\[key\]/);
assert.match(packagePanelSource, /data-comparison-state=\{right\.state\}/);
assert.match(packagePanelSource, /common\.unlimited/);
assert.match(packagePanelSource, /compare_not_included/);
assert.match(packagePanelSource, /compare_unconfigured[\s\S]*compare_unconfigured_desc/);
assert.doesNotMatch(packagePanelSource, /value == null \? '—'/, 'unknown rights must be explained instead of rendered as an ambiguous dash');
assert.match(packagePanelSource, /agency_separate_title[\s\S]*request_agency_quote/);

const packageChoicesStart = packagePanelSource.indexOf('const packageChoices');
const packageChoicesEnd = packagePanelSource.indexOf('const selectedChoice', packageChoicesStart);
const packageChoicesSource = packagePanelSource.slice(packageChoicesStart, packageChoicesEnd);
assert.doesNotMatch(packageChoicesSource, /tier: 'agency'/, 'Agency must stay outside the self-service package selector');

assert.match(packagePanelSource, /package_change_path[\s\S]*changeDetail/);
assert.match(packagePanelSource, /package_pay_price_action/);
assert.match(packagePanelSource, /package_renew_price_action/);
assert.doesNotMatch(
  packagePanelSource,
  /selectedChoice\.label[\s\S]{0,300}selectedChoice\.description/,
  'the confirmation bar must not repeat the selected package name and price description'
);

for (const key of [
  'portal.billing.package_comparison_title',
  'portal.billing.package_only_differences',
  'portal.billing.package_change_path',
  'portal.billing.agency_separate_title',
  'portal.billing.compare_not_included',
  'portal.billing.compare_unconfigured',
  'portal.billing.compare_unconfigured_desc',
]) {
  assert.equal((i18nSource.match(new RegExp(`'${key.replaceAll('.', '\\.')}'`, 'g')) || []).length, 2);
}

console.log('portal_package_comparison_contract: ok');
