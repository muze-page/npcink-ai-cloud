import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const root = process.cwd();
const billingSource = readFileSync(resolve(root, 'src/app/portal/billing/page.tsx'), 'utf8');
const usageSource = readFileSync(resolve(root, 'src/app/portal/usage/page.tsx'), 'utf8');
const creditTrendSource = readFileSync(resolve(root, 'src/components/portal/PortalCreditTrendPanel.tsx'), 'utf8');
const aiInsightsPagePath = resolve(root, 'src/app/portal/ai-insights/page.tsx');
const monitoringPagePath = resolve(root, 'src/app/portal/monitoring/page.tsx');
const sitesRedirectPagePath = resolve(root, 'src/app/portal/sites/page.tsx');
const siteServiceStatusSource = readFileSync(resolve(root, 'src/components/portal/PortalSiteServiceStatus.tsx'), 'utf8');
const siteKnowledgeSource = readFileSync(resolve(root, 'src/components/portal/PortalSiteKnowledgePanel.tsx'), 'utf8');
const siteRecordSource = readFileSync(resolve(root, 'src/app/portal/sites/[siteId]/page.tsx'), 'utf8');
const siteKnowledgePagePath = resolve(root, 'src/app/portal/site-knowledge/page.tsx');
const sitesSource = readFileSync(resolve(root, 'src/components/portal/PortalSitesWorkspace.tsx'), 'utf8');
const portalHomeSource = readFileSync(resolve(root, 'src/app/portal/page.tsx'), 'utf8');
const auditSource = readFileSync(resolve(root, 'src/app/portal/audit/PortalAuditClient.tsx'), 'utf8');
const pluginMonitoringSource = readFileSync(resolve(root, 'src/components/portal/PortalPluginMonitoringPanel.tsx'), 'utf8');
const siteInspectorSource = readFileSync(resolve(root, 'src/components/portal/PortalSiteInspectorDrawer.tsx'), 'utf8');
const i18nSource = readFileSync(resolve(root, 'src/lib/i18n.ts'), 'utf8');

assert.doesNotMatch(
  billingSource,
  /common\.tokens|common\.cost|common\.requests|snapshot_id|ledger|Ledger/,
  'Portal package page must not show tokens, cost, requests, snapshots, or ledger in the customer view'
);
assert.doesNotMatch(
  billingSource,
  /<details[\s\S]*snapshot\.snapshot_id[\s\S]*<\/details>/,
  'Portal package page must not expose package record IDs on the customer surface'
);

assert.doesNotMatch(
  usageSource,
  /usage\.tokens_month|common\.cost|remaining_tokens_test_label|remaining_cost_test_label/,
  'Portal usage must not expose token or cost counters'
);
assert.match(
  usageSource,
  /overview_title[\s\S]*view_tabs_label[\s\S]*PortalCreditTrendPanel[\s\S]*credit_events_title/,
  'Portal usage should lead with current-period totals and task tabs before their panels'
);
assert.match(
  creditTrendSource,
  /primary_trend_title[\s\S]*trend_empty_title/,
  'Portal usage trend must remain customer-facing and range based'
);
assert.match(creditTrendSource, /trend_window_1h[\s\S]*trend_window_30d/);
assert.doesNotMatch(
  usageSource,
  /Model tokens|Other provider calls|Vector articles|Vector chunks|Provider cost breakdown|Input tokens|Output tokens|usage\.tokens_month|ai-credit-ledger-v2|Rate version/,
  'Portal usage must not expose technical metering labels'
);
assert.doesNotMatch(usageSource, /PortalUsageAdvancedDetails|view_tab_details|usage-detail/);

assert.equal(
  existsSync(aiInsightsPagePath),
  false,
  'Portal service suggestions must not remain as a standalone customer page'
);
assert.equal(
  existsSync(siteKnowledgePagePath),
  false,
  'Site knowledge must remain site-scoped instead of becoming a standalone Portal page'
);

assert.doesNotMatch(
  siteServiceStatusSource,
  /Plugin monitoring|Installed plugin health|Vector observability|P95|top1|MonitoringTabs|PortalPluginMonitoringPanel|PortalMediaProcessingPanel|PortalSiteKnowledgePanel|workflow_status|evidence_summary|likely_cause|next_step|DiagnosticAdvisor|diagnosticAdvisor|suggestion_only|direct_wordpress_write|automatic_repair_allowed/,
  'Portal service status must avoid plugin/vector observability and diagnostic-advisor labels in the customer page'
);
assert.match(siteRecordSource, /<PortalSiteKnowledgePanel/);
assert.match(
  siteKnowledgeSource,
  /current_document_count[\s\S]*search_queries_total[\s\S]*no_hit_total[\s\S]*last_indexed_at/,
  'Portal site knowledge must stay limited to customer-facing coverage and recent-use facts'
);
assert.doesNotMatch(
  siteKnowledgeSource,
  /AnalyticsLineChart|AnalyticsBarChart|p95|top1|embedding_provider|embedding_model|embedding_dimensions|vector_backend|current_chunk_count|indexed_chunks_total|\.timeline|\.intents/,
  'Portal site knowledge must not expose vector internals or operator performance diagnostics'
);
assert.match(
  pluginMonitoringSource,
  /<details[\s\S]*support_event_types[\s\S]*eventKind\.event_kind[\s\S]*<\/details>/,
  'Raw connection event kinds must stay behind a support detail disclosure'
);
assert.doesNotMatch(
  siteInspectorSource,
  /translateAllowedAction|translateExternalCommercialRole|identity_type|allowed_actions|tokens_month|requests_month|resolveCustomerPackageDisplay|latest_plan_status/,
  'Portal site inspector must not show internal identity, action-scope, token, request, or package data in the customer drawer'
);
assert.doesNotMatch(
  siteInspectorSource,
  /current site, package|当前站点、订阅|current site, subscription/,
  'Portal site inspector copy must not make package or subscription look like site-owned fields'
);
assert.doesNotMatch(
  siteInspectorSource,
  /footerLinks|\/portal\/billing\?site=\$\{site\.site_id\}|\/portal\/usage\?site=\$\{site\.site_id\}|\/portal\/sites\/\$\{site\.site_id\}/,
  'Portal site inspector must not repeat global navigation as footer quick links'
);

assert.doesNotMatch(
  siteRecordSource,
  /usage\.tokens_month|usage\.requests_month|site_record_runtime_label|site_record_runtime_title|resolveCustomerPackageDisplay|common\.package|packageLabel/,
  'Portal site record must not default to runtime, token, request, or package terminology'
);
assert.match(
  siteRecordSource,
  /site_address_label[\s\S]*site_record_current_label[\s\S]*site_record_current_title/,
  'Portal site record should focus on the site address and site record status'
);
assert.doesNotMatch(
  siteRecordSource,
  /primaryAction=|secondaryActions=|href=\{`\/portal\/billing\?site=\$\{siteId\}`\}|href=\{`\/portal\/usage\?site=\$\{siteId\}`\}|portal\.site_record_service_title/,
  'Portal site record must not repeat global navigation as local quick-action cards'
);

assert.doesNotMatch(
  sitesSource,
  /site\.site_id\.toLowerCase\(\)\.includes\(query\)|account_id[^;]+includes\(query\)/,
  'Portal site search must not encourage internal site or account ID lookup'
);
assert.doesNotMatch(
  sitesSource,
  /sites_management_actions_title|handleExportFilteredSites|export_filtered_sites|select_visible_sites|remove_selected_sites|pendingBatchAction|activateSite|deactivateSite/,
  'Portal site export, activation, service toggle, and bulk management controls must not be part of the customer site list'
);
assert.doesNotMatch(
  sitesSource,
  /secondaryActions|setSiteFilter|siteFilter|setSiteSort|siteSort|all_sites_filter|sites_sort_current|sites_sort_recent|sites_sort_name/,
  'Portal site list must not expose add-site, filter-chip, or sort controls in the default customer view'
);
assert.doesNotMatch(
  sitesSource,
  /resolveCustomerPackageDisplay|getSitePackageLabel|package_card_label|current_subscription_label/,
  'Portal site list must not show account package fields inside per-site cards'
);
assert.match(
  sitesSource,
  /addonConnectMode && showConnectModal[\s\S]*PortalSiteConnectPanel/,
  'Portal site connection panel should only open from the WordPress addon return flow'
);
assert.match(
  sitesSource,
  /portal\.sites\.connect_hint_title[\s\S]*portal\.sites\.connect_hint_desc/,
  'Portal site list should explain that new site connections start from the WordPress addon'
);
assert.match(
  sitesSource,
  /const handleSelectSite = async \(siteId: string\)[\s\S]*await selectSite\(siteId\)[\s\S]*portal\.select_site_action/,
  'Portal site list must expose context switching only as an explicit customer action'
);
assert.match(
  sitesSource,
  /const selectedSiteId = session\?\.selected_context\?\.site\.site_id \|\| ''/,
  'Portal site list must read current context only from selected_context'
);
assert.match(
  sitesSource,
  /portalClient\.listAddonConnectionAccounts\(\)[\s\S]*accounts=\{addonAccounts\}/,
  'Portal addon binding must use the dedicated eligible-account candidate projection'
);
assert.doesNotMatch(
  `${sitesSource}\n${portalHomeSource}`,
  /visibleSites\.find\(\(site\) => site\.account_id\)|currentSiteId=\{firstVisibleSiteId\}|firstVisibleSiteId|sites\s*\[\s*0\s*\]|accounts\s*\[\s*0\s*\]/,
  'Portal context and addon candidates must not use site/account first-item compatibility fallbacks'
);
assert.doesNotMatch(
  portalHomeSource,
  /PortalSiteConnectPanel|\/portal\/sites\?filter=/,
  'Portal home must not embed the site creation form or link to hidden site-list filters'
);
assert.doesNotMatch(
  portalHomeSource,
  /onSelectCurrentSite|isCurrentSite|home\.select_site_action|common\.current/,
  'Portal home must not expose current-site switching controls'
);

assert.doesNotMatch(
  auditSource,
  /t\('audit\.title'|audit\.event_types|audit\.success_rate|eventKindFilter|outcomeFilter|record_type_label|all_record_types|all_results|record_count_label|range_label|apply_filters/,
  'Portal recent activity must not expose audit-log copy, advanced filters, or event-type controls'
);
assert.doesNotMatch(
  auditSource,
  /usePortalSiteSelection|selectedSiteId|getAuditBundle\(siteId|getAuditBundle\(selectedSiteId|listAuditEvents\(siteId/,
  'Portal recent activity must keep using the account-level audit projection without a site query filter'
);
assert.match(
  auditSource,
  /const contextSiteId = session\?\.selected_context\?\.site\.site_id \|\| ''[\s\S]*if \(!isAuthenticated \|\| !requestContextSiteId\) return/,
  'Portal recent activity must require an explicit selected context before loading account activity'
);
assert.match(
  auditSource,
  /useLayoutEffect\([\s\S]*setAuditEvents\(\[\]\)[\s\S]*setAuditSummary\(null\)[\s\S]*setVisibleLimit\(10\)/,
  'Portal recent activity must clear records and paging when context changes'
);
assert.match(
  auditSource,
  /portalClient\.getAuditBundle\(\{ limit \}\)/,
  'Portal recent activity must use the account-level audit bundle with the requested page size'
);
assert.match(
  auditSource,
  /loadActivity\(10\)/,
  'Portal recent activity must keep the initial account-level page bounded to 10 records'
);
assert.match(
  auditSource,
  /<details[\s\S]*portal\.support_information[\s\S]*Event ID[\s\S]*audit\.trace_id/,
  'Portal recent activity must collapse support identifiers behind support information'
);
assert.match(
  auditSource,
  /title=\{t\('portal\.audit\.nav_label'[\s\S]*portal\.audit\.recent_desc/,
  'Portal recent activity should show plain recent activity copy without a filter console'
);
assert.equal(existsSync(monitoringPagePath), false, 'retired monitoring redirect must stay deleted');
assert.equal(existsSync(sitesRedirectPagePath), false, 'retired sites redirect must stay deleted');
assert.match(
  siteRecordSource,
  /<PortalSiteServiceStatus[\s\S]*overview=\{siteMonitoring\.overview\}/,
  'Portal site record must own the customer-readable service status'
);
assert.match(
  auditSource,
  /data-portal-support-deeplink="audit"/,
  'Portal recent activity must stay available only as a support deep link'
);

for (const expectedCopy of [
  "'portal.billing.customer_title': 'Package and rights'",
  "'portal.billing.customer_title': '套餐与权益'",
  "'portal.site_record_current_label': 'Site record'",
  "'portal.site_record_current_label': '站点记录'",
  "'portal.audit.recent_desc': 'Only recent customer-readable activity is shown here.'",
  "'portal.audit.recent_desc': '这里只显示最近的客户可读活动。'",
  "'portal.usage.remaining_service_uses_label': 'Service uses left'",
  "'portal.usage.remaining_service_uses_label': '剩余服务次数'",
  "'portal.site_record': 'Open site'",
  "'portal.site_record': '查看站点'",
  "'portal.sites.connect_hint_title': 'Need to connect another site?'",
  "'portal.sites.connect_hint_title': '需要连接新站点？'",
  "'portal.home.account_status_ok_desc': 'This account can use the hosted service normally.'",
  "'portal.home.account_status_ok_desc': '当前账号可以正常使用托管服务。'",
]) {
  assert.ok(i18nSource.includes(expectedCopy), `${expectedCopy} must be present`);
}

console.log('portal_professional_info_simplification_contract: ok');
