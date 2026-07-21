import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const usagePagePath = resolve(process.cwd(), 'src/app/portal/usage/page.tsx');
const creditTrendPath = resolve(process.cwd(), 'src/components/portal/PortalCreditTrendPanel.tsx');
const i18nPath = resolve(process.cwd(), 'src/lib/i18n.ts');
const source = readFileSync(usagePagePath, 'utf8');
const creditTrendSource = readFileSync(creditTrendPath, 'utf8');
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
  'portal usage page must expose customer-readable usage records'
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
  /period_end_detail/,
  'portal usage header must show the exact period end as secondary context'
);
assert.doesNotMatch(
  headerMetricDefinition,
  /context_generated|header_updated_detail/,
  'portal usage header must not render a standalone generated-time metric'
);
assert.match(source, /updated_at_inline/, 'latest update time must remain as subtle inline context');

assert.match(
  source,
  /view_tab_trend[\s\S]*view_tab_records/,
  'trend and point records must be available as task tabs'
);
assert.doesNotMatch(source, /view_tab_details|PortalUsageAdvancedDetails|usage-detail/);
assert.doesNotMatch(source, /<details[\s\S]*data-portal-usage="ledger-detail"/);
assert.match(
  source,
  /searchParams\.get\('view'\)[\s\S]*window\.history\.replaceState[\s\S]*`\/portal\/usage/,
  'usage tabs and retired view links must keep the URL canonical'
);

assert.doesNotMatch(
  source,
  /portal-usage-site-select|portal-usage-site|creditLedgerSiteId|siteId:\s*[^\n,}]+|usePortalSiteSelection|getUsageBundle\(selectedSiteId/,
  'portal usage page must not render or depend on a site selector because usage is account-level'
);
assert.match(
  source,
  /portalClient\.getUsageBundle\(\)/,
  'portal usage page must load the account-level usage bundle'
);
assert.match(
  source,
  /const contextSiteId = session\?\.selected_context\?\.site\.site_id \|\| ''[\s\S]*if \(!isAuthenticated \|\| !requestContextSiteId\) return/,
  'account-level usage requests must fail closed until selected context exists'
);
assert.match(
  source,
  /useLayoutEffect\([\s\S]*setUsage\(null\)[\s\S]*setEntitlements\(null\)[\s\S]*setCreditEvents\(null\)[\s\S]*setCreditEventBuckets\(null\)[\s\S]*setCreditTrend\(null\)/,
  'usage must clear account projections and subresources when selected context changes'
);
assert.match(
  source,
  /selectedContext\.current_subscription[\s\S]*currentSubscription\?\.current_period_start_at[\s\S]*currentSubscription\?\.current_period_end_at/,
  'usage period context must come from the selected-context subscription contract'
);

const summaryIndex = source.indexOf('data-portal-usage="current-summary"');
const viewTabsIndex = source.indexOf('data-portal-usage="view-tabs"');
const trendIndex = source.indexOf('<PortalCreditTrendPanel');
const ledgerIndex = source.indexOf('data-portal-usage="ledger-detail"');
const recordsIndex = source.indexOf('data-portal-usage="usage-records"');

assert.ok(summaryIndex >= 0, 'current-period summary marker must exist');
assert.ok(viewTabsIndex > summaryIndex, 'usage task tabs must follow the persistent current-period summary');
assert.equal(source.indexOf('data-portal-usage="current-package"'), -1, 'current package card must move to package page');
assert.ok(trendIndex > viewTabsIndex, 'point trend must follow the usage task tabs');
assert.match(creditTrendSource, /data-portal-usage="primary-trend"/);
assert.ok(ledgerIndex > trendIndex, 'point-record tab panel must follow the trend panel');
assert.ok(recordsIndex > ledgerIndex, 'usage records must stay inside their tab panel');
assert.equal(source.indexOf("t('portal.usage.entitlement_title'"), -1, 'package entitlement detail must move to package page');
assert.equal(source.indexOf("t('portal.usage.quota_headroom_title'"), -1, 'package quota headroom must move to package page');
assert.doesNotMatch(
  source,
  /credit_packs_title|payment_orders_title|handleCreateCreditPackOrder|createCreditPackOrder/,
  'package purchase and payment order actions must live on the package page, not usage'
);
assert.match(source, /formatUsagePeriodRange[\s\S]*month:[\s\S]*day:/);
assert.match(source, /formatUsagePeriodEnd[\s\S]*year:[\s\S]*hour:/);
assert.match(source, /PORTAL_USAGE_VIEWS[^=]*= \['trend', 'records'\]/);
assert.doesNotMatch(
  source,
  /entry\.explanation|entry\.unit|formatSignedCreditDelta/,
  'customer point ledger must not render raw backend explanations, units, or signed technical deltas'
);
assert.match(
  source,
  /top_feature_key[\s\S]*credit_ledger_feature_[\s\S]*formatCreditPoints/,
  'customer point summaries must show the main feature and total points'
);
assert.match(
  source,
  /getAccountCreditEventBuckets\([\s\S]*offset: nextOffset[\s\S]*<ListPagination[\s\S]*total=\{creditEventCount\}/,
  'customer point summaries must expose filtered history through pagination'
);
assert.match(source, /creditEventBucketSize[\s\S]*'30m'[\s\S]*selectedCreditBucket/);
assert.match(source, /startAt: bucket\.start_at[\s\S]*endAt: bucket\.end_at/);
assert.match(source, /component_count[\s\S]*support_reference/);
assert.match(
  source,
  /getAccountCreditTrend\(\{[\s\S]*window: creditTrendWindow,[\s\S]*\}\)/,
  'point trend must use the account credit ledger projection without a retired site filter'
);
assert.match(
  creditTrendSource,
  /'1h'[\s\S]*'24h'[\s\S]*'7d'[\s\S]*'30d'[\s\S]*trend_empty_title[\s\S]*trend_empty_desc/,
  'point trend must provide four ranges and an explicit zero-usage state'
);
assert.doesNotMatch(
  creditTrendSource,
  /UsageBarChart[\s\S]*type="tokens"/,
  'customer point trend must not render provider token totals as points'
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
  'portal.usage.period_end_detail',
  'portal.usage.updated_at_inline',
  'portal.usage.overview_title',
  'portal.usage.overview_desc',
  'portal.usage.overview_available_detail',
  'portal.usage.period_used_label',
  'portal.usage.overview_paid_detail',
  'portal.usage.next_expiry_label',
  'portal.usage.overview_no_expiry_detail',
  'portal.usage.primary_trend_title',
  'portal.usage.primary_trend_desc',
  'portal.usage.view_tabs_label',
  'portal.usage.view_tab_trend',
  'portal.usage.view_tab_records',
  'portal.usage.trend_window_label',
  'portal.usage.trend_window_1h',
  'portal.usage.trend_window_24h',
  'portal.usage.trend_window_7d',
  'portal.usage.trend_window_30d',
  'portal.usage.trend_empty_title',
  'portal.usage.trend_empty_desc',
  'portal.usage.trend_total',
  'portal.usage.trend_chart_label',
  'portal.usage.trend_points_detail',
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
