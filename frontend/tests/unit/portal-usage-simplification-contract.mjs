import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const usagePagePath = resolve(process.cwd(), 'src/app/portal/usage/page.tsx');
const i18nPath = resolve(process.cwd(), 'src/lib/i18n.ts');
const source = readFileSync(usagePagePath, 'utf8');
const i18nSource = readFileSync(i18nPath, 'utf8');
const headerBeforeSummary = source.slice(
  source.indexOf('<PortalWorkspaceHeader'),
  source.indexOf('data-portal-usage="usage-records"')
);
const headerMetricStart = source.indexOf('const usageHeaderMetrics');
const headerMetricEnd = source.indexOf('\n\n  return (', headerMetricStart);
const headerMetricDefinition = source.slice(headerMetricStart, headerMetricEnd);

assert.match(
  source,
  /title=\{t\('portal\.nav_usage'/,
  'portal usage page must use the simplified Usage title'
);

assert.match(
  source,
  /data-portal-usage="usage-records"/,
  'portal usage page must expose usage records as the primary surface'
);
assert.doesNotMatch(
  source,
  /PortalEntitlementUsage|entitlement_usage_title|entitlement_usage_desc|entitlement_used_line/,
  'portal usage page must not repeat the package rights summary owned by the package page'
);
assert.doesNotMatch(
  headerMetricDefinition,
  /ai_credits_label|resource_bound_sites|remaining_requests_test_label/,
  'portal usage header must not repeat the detailed usage numbers shown in the current usage card'
);
assert.match(
  headerMetricDefinition,
  /header_period_detail[\s\S]*header_updated_detail/,
  'portal usage header must stay at status, period, and update context'
);

assert.doesNotMatch(
  source,
  /data-portal-usage="ledger-detail"/,
  'point records must be visible by default, not hidden behind a ledger disclosure'
);

assert.match(
  source,
  /data-portal-usage="usage-detail"/,
  'usage trends, provider cost, and entitlement detail must be grouped behind an explicit detail disclosure'
);

assert.doesNotMatch(
  source,
  /portal-usage-site-select|<select[\s\S]*selectedSiteId|usePortalSiteSelection|getUsageBundle\(selectedSiteId/,
  'portal usage page must not render or depend on a site selector because usage is account-level'
);
assert.match(
  source,
  /portalClient\.getUsageBundle\(\)/,
  'portal usage page must load the account-level usage bundle'
);

const summaryIndex = source.indexOf('data-portal-usage="usage-records"');
const detailIndex = source.indexOf('data-portal-usage="usage-detail"');
const trendsIndex = source.indexOf("t('portal.usage.trends_title'");
const costIndex = source.indexOf("t('portal.usage.cost_summary_title'");

assert.ok(summaryIndex >= 0, 'usage records marker must exist');
assert.equal(source.indexOf('data-portal-usage="current-package"'), -1, 'current package card must move to package page');
assert.ok(detailIndex > summaryIndex, 'usage details must stay after the usage summary');
assert.ok(trendsIndex > detailIndex, 'usage trends must be inside the detail disclosure');
assert.ok(costIndex > detailIndex, 'provider cost summary must be inside the detail disclosure');
assert.equal(source.indexOf("t('portal.usage.entitlement_title'"), -1, 'package entitlement detail must move to package page');
assert.equal(source.indexOf("t('portal.usage.quota_headroom_title'"), -1, 'package quota headroom must move to package page');
assert.doesNotMatch(
  source,
  /credit_packs_title|payment_orders_title|handleCreateCreditPackOrder|createCreditPackOrder/,
  'package purchase and payment order actions must live on the package page, not usage'
);
assert.match(
  source,
  /chartTotals[\s\S]*trend_service_detail[\s\S]*trend_points_detail[\s\S]*trend_budget_detail[\s\S]*trend_empty/,
  'usage trend cards must show totals and an explicit empty state instead of blank chart panels'
);
assert.doesNotMatch(
  source,
  /entry\.explanation|entry\.unit|formatSignedCreditDelta/,
  'customer point ledger must not render raw backend explanations, units, or signed technical deltas'
);
assert.match(
  source,
  /feature_key[\s\S]*credit_ledger_feature_[\s\S]*credit_ledger_service_used_suffix[\s\S]*credit_ledger_credit_deducted/,
  'customer point ledger must show the concrete backend-provided feature and point deduction copy'
);
assert.doesNotMatch(
  source,
  /formatLedgerQuantity|credit_ledger_quantity/,
  'customer point ledger must remove the repeated quantity column'
);
assert.doesNotMatch(
  source,
  /currentPeriodLabel[\s\S]*period_label[\s\S]*formatCurrentUsageLine[\s\S]*used_label[\s\S]*included_label[\s\S]*formatOverageLine[\s\S]*overage_line/,
  'usage page must not show package included/remaining quota copy after the package page owns rights'
);

for (const key of [
  'portal.usage.summary_label',
  'portal.usage.summary_title',
  'portal.usage.summary_desc',
  'portal.usage.header_period_detail',
  'portal.usage.header_updated_detail',
  'portal.usage.detail_toggle',
  'portal.usage.trend_empty',
  'portal.usage.trend_service_detail',
  'portal.usage.trend_points_detail',
  'portal.usage.trend_budget_detail',
  'portal.usage.period_label',
  'portal.usage.used_label',
  'portal.usage.included_label',
  'portal.usage.overage_line',
  'portal.usage.unit_times',
  'portal.usage.unit_points',
  'portal.usage.credit_ledger_ai_service_title',
  'portal.usage.credit_ledger_feature_content_generation_title',
  'portal.usage.credit_ledger_feature_content_generation_detail',
  'portal.usage.credit_ledger_feature_topic_research_title',
  'portal.usage.credit_ledger_feature_topic_research_detail',
  'portal.usage.credit_ledger_feature_web_search_title',
  'portal.usage.credit_ledger_feature_web_search_detail',
  'portal.usage.credit_ledger_feature_site_knowledge_title',
  'portal.usage.credit_ledger_feature_site_knowledge_detail',
  'portal.usage.credit_ledger_feature_image_assistance_title',
  'portal.usage.credit_ledger_feature_image_assistance_detail',
  'portal.usage.credit_ledger_feature_audio_generation_title',
  'portal.usage.credit_ledger_feature_audio_generation_detail',
  'portal.usage.credit_ledger_service_used_desc',
  'portal.usage.credit_ledger_service_used_suffix',
  'portal.usage.credit_ledger_credit_deducted',
]) {
  assert.match(i18nSource, new RegExp(`'${key}'`), `${key} must be translated`);
}

assert.doesNotMatch(
  i18nSource,
  /credit_ledger_feature_ai_assistance|credit_ledger_ai_service_title': '智能功能/,
  'customer point ledger must not expose vague AI assistance fallback copy'
);
assert.doesNotMatch(
  i18nSource,
  /portal\.usage\.credit_ledger_quantity/,
  'customer point ledger translations must not keep the removed quantity column'
);

console.log('portal_usage_simplification_contract: ok');
