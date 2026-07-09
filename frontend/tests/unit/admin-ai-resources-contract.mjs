import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const pagePath = resolve(process.cwd(), 'src/app/admin/ai-resources/page.tsx');
const abilityModelsPath = resolve(process.cwd(), 'src/app/admin/ability-models/page.tsx');
const aiAdvisorPath = resolve(process.cwd(), 'src/app/admin/ai-advisor/page.tsx');
const layoutPath = resolve(process.cwd(), 'src/app/admin/layout.tsx');
const troubleshootingPath = resolve(process.cwd(), 'src/app/admin/troubleshooting/page.tsx');
const webSearchPagePath = resolve(process.cwd(), 'src/app/admin/web-search/page.tsx');
const imageSourcesPagePath = resolve(process.cwd(), 'src/app/admin/image-sources/page.tsx');
const portalSiteConnectPanelPath = resolve(process.cwd(), 'src/components/portal/PortalSiteConnectPanel.tsx');
const portalNavbarPath = resolve(process.cwd(), 'src/components/portal/PortalNavbar.tsx');
const portalAuditPath = resolve(process.cwd(), 'src/app/portal/audit/PortalAuditClient.tsx');
const adminPortalUsersPath = resolve(process.cwd(), 'src/app/admin/portal-users/page.tsx');
const adminSubscriptionDetailPath = resolve(process.cwd(), 'src/app/admin/subscriptions/[subscriptionId]/page.tsx');
const workflowMetadataPanelPath = resolve(process.cwd(), 'src/components/backoffice/CloudWorkflowMetadataPanel.tsx');
const adminLoginPath = resolve(process.cwd(), 'src/app/admin/login/page.tsx');
const pageSource = readFileSync(pagePath, 'utf8');
const abilityModelsSource = readFileSync(abilityModelsPath, 'utf8');
const aiAdvisorSource = readFileSync(aiAdvisorPath, 'utf8');
const layoutSource = readFileSync(layoutPath, 'utf8');
const troubleshootingSource = readFileSync(troubleshootingPath, 'utf8');
const portalSiteConnectSource = readFileSync(portalSiteConnectPanelPath, 'utf8');
const portalNavbarSource = readFileSync(portalNavbarPath, 'utf8');
const portalAuditSource = readFileSync(portalAuditPath, 'utf8');
const adminPortalUsersSource = readFileSync(adminPortalUsersPath, 'utf8');
const adminSubscriptionDetailSource = readFileSync(adminSubscriptionDetailPath, 'utf8');
const workflowMetadataPanelSource = readFileSync(workflowMetadataPanelPath, 'utf8');
const adminLoginSource = readFileSync(adminLoginPath, 'utf8');
const i18nSource = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');
const openCapabilityTemplateStart = pageSource.indexOf('function openCapabilityProviderTemplate');
const openCapabilityTemplateSource = openCapabilityTemplateStart >= 0
  ? pageSource.slice(openCapabilityTemplateStart, pageSource.indexOf('const resourceStatusLabel', openCapabilityTemplateStart))
  : '';
const capabilityDiagnosticsStart = pageSource.indexOf('capability_diagnostics_title');
const capabilityDiagnosticsSource = capabilityDiagnosticsStart >= 0
  ? pageSource.slice(capabilityDiagnosticsStart, pageSource.indexOf('{providerUsesCustomRuntimeFields', capabilityDiagnosticsStart))
  : '';
const capabilitySupplierTableStart = pageSource.indexOf('activeCapabilityConnections.map');
const capabilitySupplierTableSource = capabilitySupplierTableStart >= 0
  ? pageSource.slice(pageSource.lastIndexOf('<table', capabilitySupplierTableStart), pageSource.indexOf('{capabilityAddDialogOpen', capabilitySupplierTableStart))
  : '';
const connectionsToolbarStart = pageSource.indexOf("activeView === 'connections'");
const connectionsToolbarSource = connectionsToolbarStart >= 0
  ? pageSource.slice(connectionsToolbarStart, pageSource.indexOf("{supplierTypeFilter === 'model' || providerFormOpen", connectionsToolbarStart))
  : '';
const aiResourcesPrimaryPanelStart = pageSource.indexOf("description={aiText('description'");
const aiResourcesPrimaryPanelSource = aiResourcesPrimaryPanelStart >= 0
  ? pageSource.slice(aiResourcesPrimaryPanelStart, pageSource.indexOf('</BackofficePrimaryPanel>', aiResourcesPrimaryPanelStart))
  : '';
const autoSyncModelReferencesStart = pageSource.indexOf('const autoSyncModelReferences');
const autoSyncModelReferencesSource = autoSyncModelReferencesStart >= 0
  ? pageSource.slice(autoSyncModelReferencesStart, pageSource.indexOf('async function runProviderConnectionTest', autoSyncModelReferencesStart))
  : '';

const aiResourcesNavIndex = layoutSource.indexOf("href: '/admin/ai-resources'");
const abilityModelsNavIndex = layoutSource.indexOf("href: '/admin/ability-models'");
const troubleshootingNavIndex = layoutSource.indexOf("href: '/admin/troubleshooting'");
const troubleshootingNavBlock = layoutSource.slice(
  troubleshootingNavIndex,
  layoutSource.indexOf('const isPathMatch', troubleshootingNavIndex)
);

assert.ok(
  aiResourcesNavIndex >= 0,
  'AI resources must have a top-level admin navigation entry'
);

assert.ok(
  abilityModelsNavIndex >= 0,
  'Ability-model routing must have a top-level admin navigation entry'
);

assert.ok(
  aiResourcesNavIndex < troubleshootingNavIndex,
  'Providers must appear before Runtime Diagnostics in primary navigation'
);

assert.ok(
  aiResourcesNavIndex < abilityModelsNavIndex && abilityModelsNavIndex < troubleshootingNavIndex,
  'Model binding must sit beside Providers before Runtime Diagnostics'
);

assert.doesNotMatch(
  troubleshootingNavBlock,
  /\/admin\/ai-resources|\/admin\/ability-models/,
  'Runtime Diagnostics must not own the provider or model binding active paths'
);

assert.doesNotMatch(
  troubleshootingNavBlock,
  /\/admin\/wordpress-ai-routing/,
  'Runtime Diagnostics must not keep the legacy WordPress AI routing path active'
);

assert.doesNotMatch(
  portalSiteConnectSource,
  /connect_site_current_customer|portal\.support_information|BackofficeIdentifier value=\{accountId/,
  'Portal site connect must not expose customer/account IDs or support information in the binding flow'
);

assert.match(
  portalSiteConnectSource,
  /isAddonConnection \? \([\s\S]*addonSiteLabel[\s\S]*wordpressUrl\.trim\(\)[\s\S]*\) : null/,
  'Portal addon connection must show a simple read-only site summary from the WordPress return payload'
);

assert.match(
  portalSiteConnectSource,
  /!\s*isAddonConnection \? \([\s\S]*portal\.connect_site_url_label[\s\S]*type="url"[\s\S]*\) : null/,
  'Portal addon connection must not render the editable WordPress URL input'
);

assert.doesNotMatch(
  portalSiteConnectSource,
  /getPortalSiteDisplayName\(currentSite\)/,
  'Portal site connect must not let the display-name helper fall back to a site ID in the default card'
);

assert.match(
  portalNavbarSource,
  /site\.site_id\.toLowerCase\(\)/,
  'Portal site switcher must keep site IDs searchable'
);

assert.match(
  portalNavbarSource,
  /visibleSiteLabel[\s\S]*getPortalSiteWordPressUrl/,
  'Portal site switcher must keep site IDs searchable while avoiding ID fallback in the visible label'
);

assert.doesNotMatch(
  portalNavbarSource,
  /getPortalSiteSecondaryLabel\(site\) \|\| site\.site_id|getPortalSiteSecondaryLabel\(selectedSite\)/,
  'Portal site switcher must not show site IDs as the default secondary label'
);

assert.match(
  portalAuditSource,
  /portal\.support_information[\s\S]*Event ID[\s\S]*audit\.trace_id/,
  'Portal audit must keep event and trace identifiers inside support information'
);

assert.match(
  adminPortalUsersSource,
  /admin\.portal_users\.request_technical_detail[\s\S]*event\.trace_id[\s\S]*event\.idempotency_key/,
  'Admin portal user audit cards must collapse raw request fields into technical details'
);

assert.match(
  adminSubscriptionDetailSource,
  /resolveAdminPackageLabel[\s\S]*portal\.support_information[\s\S]*BackofficeIdentifier value=\{normalized\.subscriptionId\}/,
  'Subscription detail must lead with package/customer labels and keep subscription IDs in support information'
);

assert.doesNotMatch(
  adminSubscriptionDetailSource,
  /<BackofficeIdentifier\s+value=\{normalized\.subscriptionId\}\s+className="mt-3 block/,
  'Subscription detail must not use the subscription ID as the primary title line'
);

assert.match(
  workflowMetadataPanelSource,
  /workflow_metadata\.write_posture[\s\S]*workflow_metadata\.review_posture[\s\S]*workflow_metadata\.technical_metadata[\s\S]*workflow_metadata\.workflow/,
  'Workflow metadata panel must show governance conclusions first and move raw workflow metadata into technical details'
);

assert.match(
  adminLoginSource,
  /portal\.support_information[\s\S]*Trace: \{traceId\}/,
  'Admin login must move trace IDs into support information'
);

assert.doesNotMatch(
  adminLoginSource,
  /` · Trace: \$\{traceId\}`/,
  'Admin login errors must not append trace IDs to the default error line'
);

assert.equal(
  existsSync(resolve(process.cwd(), 'src/app/admin/wordpress-ai-routing/page.tsx')),
  false,
  'Legacy WordPress AI routing UI page must be removed after Model Binding becomes the only UI entry'
);

assert.doesNotMatch(
  layoutSource,
  /activePrefixes: \['\/admin\/ai-resources', '\/admin\/wordpress-ai-routing'\]/,
  'Provider navigation must not keep the legacy WordPress AI routing UI path active'
);

assert.doesNotMatch(
  troubleshootingSource,
  /\/admin\/ai-resources|Related operations|action_open_ai_resources/,
  'Advanced Troubleshooting must not expose Provider Management as a related operations entry'
);

assert.doesNotMatch(
  troubleshootingSource,
  /Top-level model and capability supplier operations/,
  'Advanced Troubleshooting must not keep duplicate Provider Management helper copy'
);

assert.doesNotMatch(
  `${layoutSource}\n${troubleshootingSource}\n${i18nSource}`,
  /\/admin\/hosted-models|admin\.nav_hosted_models|admin\.hosted_models\.|admin\.advanced\.hosted_models_desc/,
  'Standalone Hosted Models navigation, troubleshooting copy, and page translations must be removed'
);

assert.match(
  pageSource,
  /useLocale/,
  'AI resources page must use the shared locale system'
);

assert.match(
  pageSource,
  /admin\.ai_resources\./,
  'AI resources page must route static UI copy through admin.ai_resources translations'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.title': '供应商'/,
  'AI resources page must provide Simplified Chinese supplier translations'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.description': '管理 Cloud 运行时 provider 连接、模型可见性和能力来源。运行诊断保留在运行诊断页。'/,
  'AI resources page description must frame the surface as Cloud runtime provider operations'
);

assert.match(
  i18nSource,
  /'admin\.nav_ai_resources': '供应商'/,
  'Top-level admin navigation must use compact Simplified Chinese provider copy'
);

assert.match(
  i18nSource,
  /'admin\.nav_ability_models': '模型绑定'/,
  'Top-level admin navigation must expose Model Binding in Simplified Chinese'
);

assert.match(
  i18nSource,
  /'admin\.nav_ai_advisor': '运营诊断助手'/,
  'Advanced troubleshooting navigation must expose AI Advisor as Operations Advisor in Simplified Chinese'
);

assert.match(
  aiAdvisorSource,
  /admin\.ai_advisor\.title[\s\S]*admin\.ai_advisor\.description[\s\S]*admin\.ai_advisor\.action_run_diagnosis/,
  'AI Advisor page shell must route visible operator copy through admin.ai_advisor translations'
);

assert.match(
  aiAdvisorSource,
  /function OperationsWorkPanel[\s\S]*recommendedActions[\s\S]*actionDisplay/,
  'AI Advisor default surface must lead with operational recommendations instead of AI evaluation metrics'
);

assert.match(
  aiAdvisorSource,
  /statusLabel\(status, t\)[\s\S]*severityLabel\(severity, t\)[\s\S]*actionDisplay\(item\.action, t\)/,
  'AI Advisor operational status and action copy must remain locale-aware'
);

assert.match(
  aiAdvisorSource,
  /<OperationsWorkPanel data=\{data\} \/>[\s\S]*<SignalPanel branch=\{data\.ai\} \/>[\s\S]*<AdvisorEvaluationDetails>/,
  'AI Advisor must show current diagnosis and evidence before the advanced AI evaluation details'
);

assert.match(
  i18nSource,
  /'admin\.ai_advisor\.description': '查看当前 Cloud 运营信号、下一步处理动作和可追溯证据。AI 对比与成本评估放在高级详情里。'/,
  'AI Advisor Simplified Chinese description must explain the operator problem it solves'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.window_last_24h': '最近 24 小时'/,
  'AI resources health windows must provide Simplified Chinese labels'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.status_missing_secret_label': '缺少密钥'/,
  'AI resources provider status labels must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.test_stage_web_search_probe': '搜索探测'[\s\S]*'admin\.ai_resources\.test_message_web_search_candidates': '搜索供应商返回 \{\{count\}\} 条候选来源。'/,
  'AI resources provider test diagnostics must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.test_stage_web_search_reader_probe': '读取探测'[\s\S]*'admin\.ai_resources\.test_message_web_search_reader_candidates': '网页读取增强返回 \{\{count\}\} 个可读取来源。'/,
  'AI resources Jina Reader diagnostics must be labeled as reader enhancement copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.test_passed': '通过'[\s\S]*'admin\.ai_resources\.test_failed': '失败'/,
  'AI resources compact test summaries must provide Simplified Chinese labels'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.column_provider': '供应商'/,
  'AI resources provider table headings must provide Simplified Chinese copy'
);

assert.match(
  pageSource,
  /fetch\('\/api\/admin\/ai-resources'/,
  'AI resources page must read the shared admin AI resources projection'
);

assert.match(
  pageSource,
  /recent_minutes: '1440'[\s\S]*limit: '25'[\s\S]*fetch\(`\/api\/admin\/runtime-telemetry\?\$\{params\.toString\(\)\}`/,
  'Provider Management diagnostics must read the live runtime telemetry projection'
);

assert.doesNotMatch(
  pageSource,
  /runtime_telemetry_boundary_notice[\s\S]*run_records[\s\S]*provider_call_records[\s\S]*usage_meter_events/,
  'Provider Management must not keep the full runtime telemetry evidence panel'
);

assert.doesNotMatch(
  i18nSource,
  /'admin\.ai_resources\.runtime_telemetry_boundary_notice'/,
  'Runtime telemetry evidence copy must move out of the Provider Management namespace'
);

assert.match(
  pageSource,
  /useState<AIResourceView>\('connections'\)/,
  'AI resources page must default directly to the supplier workflow'
);

assert.match(
  pageSource,
  /useState<SupplierTypeFilter>\('model'\)/,
  'AI resources page must default to the shorter model-supplier work surface'
);

assert.doesNotMatch(
  pageSource,
  /active=\{activeView === 'connections' && activeSupplierTab === 'model'\}[\s\S]*active=\{activeView === 'diagnostics'\}/,
  'AI resources must not render a second supplier/diagnostics top-level tab row above the supplier settings panel'
);

assert.match(
  pageSource,
  /href="\/admin\/troubleshooting"[\s\S]*action_view_diagnostics/,
  'Provider management diagnostics must route to the Runtime Diagnostics page instead of expanding inside suppliers'
);

assert.match(
  pageSource,
  /role="tablist"[\s\S]*supplier_filter_model[\s\S]*supplier_filter_capability/,
  'Supplier type switching must be a compact same-object tab row instead of a long dropdown'
);

assert.doesNotMatch(
  connectionsToolbarSource,
  /filter_all_supplier_types/,
  'Supplier type switching must not include a redundant all-suppliers tab'
);

assert.doesNotMatch(
  pageSource,
  /onClick=\{\(\) => setActiveView\('diagnostics'\)\}/,
  'AI resources page must not expose an in-page diagnostics switch from the supplier header'
);

assert.doesNotMatch(
  pageSource,
  /activeView === 'diagnostics' && activeDiagnosticView === 'matrix'/,
  'Runtime resolution, capability matrix, runtime profiles, and recent evidence must not remain as hidden Provider Management diagnostics'
);

assert.match(
  pageSource,
  /providerTestStageLabel\(testResult\.stage\)[\s\S]*providerTestMessage\(testResult\)/,
  'Provider test results must render through localized stage and message helpers'
);

assert.match(
  pageSource,
  /web_search_reader_probe[\s\S]*test_message_web_search_reader_candidates/,
  'Provider test results must treat Jina Reader as a reader probe instead of a primary search probe'
);

assert.doesNotMatch(
  pageSource,
  /\{testResult\.stage\}|\{testResult\.message\}/,
  'Provider test results must not render raw backend diagnostics'
);

assert.doesNotMatch(
  pageSource,
  /active=\{activeView === 'overview'\}/,
  'AI resources overview must not remain a top-level default tab'
);

assert.match(
  pageSource,
  /requestedView === 'overview'[\s\S]*setActiveView\('connections'\)/,
  'Legacy overview deep links must land on suppliers instead of restoring a separate overview page'
);

assert.match(
  abilityModelsSource,
  /fetch\('\/api\/admin\/ability-models\/plugin-routing'/,
  'Ability-model routing page must save bounded plugin ability routes through the ability-model plugin routing endpoint'
);

assert.doesNotMatch(
  abilityModelsSource,
  /fetch\('\/api\/admin\/wordpress-ai-routing'/,
  'Ability-model routing page must not keep the retired WordPress AI routing compatibility endpoint'
);

assert.doesNotMatch(
  abilityModelsSource,
  /profile-preferences|saveProfilePreferences/,
  'Ability-model routing page must not keep a separate profile-preferences write path after audio routes move into routing profiles'
);

assert.match(
  abilityModelsSource,
  /type AbilityModelTab = 'wordpress' \| 'cloud'/,
  'Ability-model routing page must keep only WordPress and Cloud-native top-level tabs explicitly'
);

assert.match(
  abilityModelsSource,
  /type CloudAbilityMediaTab = 'text' \| 'image' \| 'vector' \| 'audio' \| 'video'/,
  'Cloud-native runtime abilities must be grouped by text, image, vector, audio, and video media tabs'
);

assert.match(
  abilityModelsSource,
  /useState<AbilityModelTab>\('wordpress'\)/,
  'Ability-model routing page must default to the plugin ability defaults tab'
);

assert.match(
  abilityModelsSource,
  /tab_wordpress[\s\S]*tab_cloud/,
  'Ability-model routing page must expose plugin ability and Cloud-native top-level tabs'
);

assert.doesNotMatch(
  abilityModelsSource,
  /activeAbilityTab === 'audio'|tab_audio/,
  'Audio ability-model routes must not remain a top-level ability tab'
);

assert.match(
  abilityModelsSource,
  /CLOUD_MEDIA_ORDER: CloudAbilityMediaTab\[\] = \['text', 'image', 'vector', 'audio', 'video'\][\s\S]*availableCloudMediaTabs\.map[\s\S]*cloud_media_tab_\$\{tab\}/,
  'Cloud runtime dependencies must keep a stable media order but only render category filters that exist in current rows'
);

assert.match(
  abilityModelsSource,
  /wordpress_title[\s\S]*abilityModelRows\.map/,
  'Plugin ability-model routing table must render unified routing profile rows'
);

assert.match(
  abilityModelsSource,
  /available_audio_instances[\s\S]*execution_kind === 'audio_generation'[\s\S]*available_audio_instances/,
  'Audio ability-model routes must use the shared WordPress AI routing projection and audio runtime candidates'
);

assert.doesNotMatch(
  abilityModelsSource,
  /profileKindLabel: string/,
  'Audio ability-model routes must not expose internal profile kind labels as a default table column'
);

assert.doesNotMatch(
  abilityModelsSource,
  /type AudioAbilityModelRouteRow|audioPreferenceRows/,
  'Audio ability-model routes must not keep a separate page-local preference row model'
);

assert.doesNotMatch(
  i18nSource,
  /Cloud 运行时 profile|profile 偏好|当前 profile|配置 profile|文本 profile|音频 profile/,
  'Ability-model routing copy must not expose internal profile terminology as user-facing Chinese labels'
);

assert.match(
  abilityModelsSource,
  /audio_summary_script[\s\S]*article_narration[\s\S]*article_audio_summary/,
  'Unified plugin ability route rows must include the audio summary, narration, and summary playback scenarios'
);

assert.doesNotMatch(
  abilityModelsSource + i18nSource,
  /cloud_ability_audio_summary_script|cloud_ability_article_narration|cloud_ability_article_audio_summary/,
  'Cloud runtime dependency projection must not re-label plugin-owned audio routes as Cloud-owned dependencies'
);

assert.doesNotMatch(
  abilityModelsSource,
  /audioPreferenceRows\.map[\s\S]*<select[\s\S]*saveProfilePreferences|openAudioRouteDialog|activeAudioRoute/,
  'Audio ability-model route rows must not place selectors and save buttons inside the narrow table action column'
);

assert.doesNotMatch(
  abilityModelsSource,
  /mt-4 grid gap-4 lg:grid-cols-3[\s\S]*audio_summary_text_profile_id/,
  'Audio ability-model routes must not use the old three-column field layout'
);

assert.doesNotMatch(
  abilityModelsSource,
  /audio_summary_text_profile_id|audio_narration_profile_id|audio_summary_audio_profile_id/,
  'Audio ability-model routes must not expose legacy profile preference keys after moving into routing profiles'
);

assert.doesNotMatch(
  pageSource,
  /activeSupplierTab === 'model' && preferences/,
  'AI resource audio profile preferences must not stay under the model supplier tab'
);

assert.doesNotMatch(
  pageSource,
  /profile_preferences|audio_summary_text_profile_id|audio_narration_profile_id|audio_summary_audio_profile_id/,
  'AI resources page must not keep the old audio profile preference surface after routing moved to ability models'
);

assert.match(
  abilityModelsSource,
  /activeProfileIsAudioGeneration[\s\S]*createAudioPreview[\s\S]*preview_instance_id[\s\S]*inspector_tab_preview[\s\S]*<audio className="w-full" controls/,
  'Ability-model audio route dialog must support in-dialog audio preview without saving the route'
);

assert.match(
  abilityModelsSource,
  /\/api\/admin\/audio-preview\?url=\$\{encodeURIComponent\(audio\.url\)\}/,
  'Ability-model audio preview must use the same-origin audio preview proxy'
);

assert.doesNotMatch(
  layoutSource,
  /\/admin\/audio-workbench/,
  'Admin primary navigation must not expose the standalone audio workbench after preview moved into ability-model routing'
);

assert.doesNotMatch(
  troubleshootingSource,
  /\/admin\/audio-workbench|action_open_audio_workbench|nav_audio_workbench/,
  'Advanced troubleshooting catalog must not expose the standalone audio workbench as a routine entry'
);

assert.doesNotMatch(
  pageSource,
  /tab_ability_models/,
  'Provider Management must not expose Ability-Model Routing as an internal tab'
);

assert.doesNotMatch(
  pageSource,
  /ability_models_title|abilityModelDialog|RoutingProfile|RuntimeInstance|fetch\('\/api\/admin\/wordpress-ai-routing'|fetch\('\/api\/admin\/ability-models\/plugin-routing'|saveAbilityModelProfile|activeView === 'ability_models'/,
  'Provider Management must not keep a hidden ability-model routing editor after routing moved to the dedicated page'
);

assert.match(
  pageSource,
  /value=\{connectionStatusFilter\}[\s\S]*setConnectionStatusFilter[\s\S]*status_filter_label[\s\S]*filter_ready[\s\S]*filter_missing_secret[\s\S]*filter_disabled/,
  'Provider channel status filtering must live in a status-column select'
);

assert.match(
  connectionsToolbarSource,
  /<span className="sr-only">\{aiText\('field_search_connections'[\s\S]*action_add_model_supplier[\s\S]*action_add_capability_supplier/,
  'Provider channel toolbar must keep search and the active supplier add action without duplicate filter controls'
);

assert.match(
  capabilitySupplierTableSource,
  /value=\{capabilityCategoryFilter\}[\s\S]*setCapabilityCategoryFilter[\s\S]*capability_category_filter/,
  'Capability supplier category filtering must live in the category-column select'
);

assert.match(
  capabilitySupplierTableSource,
  /w-36[\s\S]*filter_all_categories[\s\S]*w-36[\s\S]*filter_all_statuses/,
  'Capability supplier header filters must use explicit all-category and all-status labels with consistent width'
);

assert.doesNotMatch(
  connectionsToolbarSource,
  /capability_category_filter|status_filter_label|connectionStatusFilter/,
  'Provider channel toolbar must not duplicate category or status filter controls'
);

assert.match(
  pageSource,
  /supplierTypeFilter === 'model' \|\| providerFormOpen/,
  'Provider channel form must render when opened from capability suppliers as well as model suppliers'
);

assert.match(
  pageSource,
  /isCapabilityProviderForm \? \([\s\S]*field_channel_priority[\s\S]*field_channel_note[\s\S]*placeholder_channel_note/,
  'Provider channel form must keep priority scoped to capability suppliers and keep notes available for channels'
);

assert.match(
  pageSource,
  /note: providerConnectionForm\.note[\s\S]*priority: Number\(providerConnectionForm\.priority\)/,
  'Provider channel save payload must persist channel note and priority metadata'
);

assert.doesNotMatch(
  pageSource,
  /supplierGroup\.connections\.map[\s\S]*channel_priority_summary[\s\S]*model_catalog_enabled_count/,
  'Model supplier list must not show provider priority because routing priority belongs to model-call configuration'
);

assert.match(
  pageSource,
  /addProviderCredentialChannel[\s\S]*credential: ''[\s\S]*action_add_credential_channel/,
  'Provider channel form must let operators add a credential channel without copying the secret'
);

assert.match(
  capabilitySupplierTableSource,
  /capabilityProviderPurposeLabel\(connection\)[\s\S]*status_configured_label[\s\S]*showPriority[\s\S]*channel_priority_summary/,
  'Capability supplier table must keep priority in the connection column instead of the supplier identity column'
);

assert.match(
  pageSource,
  /activeCapabilityConnections\.map[\s\S]*onClick=\{\(\) => \{[\s\S]*editProviderConnection\(connection\)/,
  'Capability supplier Configure action must open the shared provider connection form'
);

assert.match(
  capabilitySupplierTableSource,
  /column_provider[\s\S]*capability_category_filter[\s\S]*status_filter_label[\s\S]*column_connection[\s\S]*last_test[\s\S]*column_actions/,
  'Capability supplier list must use provider/category-filter/status-filter/connection/test/actions columns'
);

assert.doesNotMatch(
  capabilitySupplierTableSource,
  /column_profiles|column_enabled_configured/,
  'Capability supplier list must not expose profile id or verbose enabled/configured columns'
);

assert.doesNotMatch(
  capabilitySupplierTableSource,
  /connectionHost\(connection\.base_url\)|connection\.base_url/,
  'Capability supplier list must keep endpoint/base URL details out of the main table'
);

assert.match(
  capabilitySupplierTableSource,
  /capabilityProviderPurposeLabel\(connection\)[\s\S]*capabilityCategoryLabel\(category\)[\s\S]*status_configured_label/,
  'Capability supplier list must show supplier purpose, category column, and compact configured state'
);

assert.match(
  pageSource,
  /connectionSearch[\s\S]*connection\.base_url/,
  'Capability supplier endpoints must remain searchable even when hidden from the main table'
);

assert.doesNotMatch(
  pageSource,
  /ai_suppliers_title|capability_supplier_list_title|capability_supplier_list_desc/,
  'Supplier tables must not keep redundant inner list titles or helper copy'
);

assert.doesNotMatch(
  capabilitySupplierTableSource,
  /label=\{connection\.enabled \? aiText\('field_enabled'[\s\S]*status=\{connection\.enabled \? 'success'/,
  'Capability supplier connection state must use quiet text instead of success badges for normal enabled/configured state'
);

assert.match(
  capabilitySupplierTableSource,
  /connectionTestResults\[connection\.connection_id\][\s\S]*runProviderConnectionTest\(connection\.connection_id\)/,
  'Capability supplier list must expose a per-connection self-test action'
);

assert.match(
  capabilitySupplierTableSource,
  /test_passed[\s\S]*formatDate\(connection\.last_tested_at\)/,
  'Capability supplier last-test success state must render as a compact text summary'
);

assert.doesNotMatch(
  capabilitySupplierTableSource,
  /BackofficeStatusBadge label=\{aiText\('status_ready_label'[\s\S]*status="success"/,
  'Capability supplier last-test success state must not render a visually heavy ready badge'
);

assert.doesNotMatch(
  capabilitySupplierTableSource,
  /cloud-checks|toolbox_tab/,
  'Capability supplier self-test must not embed the Toolbox Cloud Checks end-to-end surface'
);

assert.doesNotMatch(
  pageSource,
  /capability_suppliers_inline_notice/,
  'Capability supplier list must not keep a default explanatory notice above the working table'
);

assert.match(
  pageSource,
  /fetch\('\/api\/admin\/provider-connections'/,
  'AI resources page must save provider connections through the bounded admin endpoint'
);

assert.match(
  pageSource,
  /fetch\('\/api\/admin\/provider-connections\/preview-catalog'/,
  'AI resources page must preview upstream models through the bounded provider catalog preview endpoint'
);

assert.match(
  abilityModelsSource,
  /fetch\('\/api\/admin\/ability-models\/plugin-routing'/,
  'Ability-model routing page must load and save Cloud runtime ability-model routing through the bounded admin endpoint'
);

assert.match(
  abilityModelsSource,
  /routing_intent: string[\s\S]*routing_intent: String\(profile\?\.routing_intent/,
  'Ability-model routing page must consume backend routing_intent metadata'
);

assert.doesNotMatch(
  abilityModelsSource,
  /row\.profile\.routing_intent \|\| row\.profile\.label/,
  'Ability-model routing rows must not default-display internal routing intent identifiers'
);

assert.doesNotMatch(
  abilityModelsSource,
  /<div className="mt-1 font-mono text-sm md:mt-0">\{row\.profile\.profile_id\}<\/div>/,
  'Ability-model routing rows must not default-display internal profile ids such as wp-ai.short-text'
);

assert.doesNotMatch(
  abilityModelsSource,
  /<div className="mt-1 text-xs text-slate-500 dark:text-slate-400">\{activeProfile\.profile_id\}<\/div>/,
  'Ability-model routing dialog must not default-display internal profile ids such as wp-ai.short-text'
);

assert.match(
  abilityModelsSource,
  /normalizeProviderDisplayNames[\s\S]*display_name[\s\S]*setProviderDisplayNames/,
  'Ability-model routing page must load provider display names from Provider Management instead of showing adapter ids as supplier names'
);

assert.match(
  abilityModelsSource,
  /isModelProviderConnection[\s\S]*web_search_provider[\s\S]*image_source_provider[\s\S]*embedding_provider[\s\S]*vector_store_provider[\s\S]*normalizeProviderDisplayNames/,
  'Ability-model routing supplier filter must exclude non-model capability providers such as search, image-source, embedding, and vector-store connections'
);

assert.match(
  abilityModelsSource,
  /modelRouteLabel[\s\S]*providerDisplayName[\s\S]*providerLabel} \/ \$\{normalizedModelId/,
  'Ability-model routing table must present current model as provider display name plus model id'
);

assert.match(
  abilityModelsSource,
  /modelProviderFilter[\s\S]*field_model_provider_filter[\s\S]*providerOptions/,
  'Ability-model routing dialog must provide supplier filtering for runtime model candidates'
);

assert.match(
  abilityModelsSource,
  /Object\.entries\(providerDisplayNames\)[\s\S]*candidateCountsByProvider[\s\S]*candidateCount/,
  'Ability-model routing supplier filter must show Provider Management suppliers even when the current ability has zero candidates for that supplier'
);

assert.match(
  abilityModelsSource,
  /disabled=\{option\.candidateCount === 0\}/,
  'Ability-model routing supplier filter must keep zero-candidate suppliers visible but not selectable for the current ability'
);

assert.match(
  abilityModelsSource,
  /model_search_empty_hint[\s\S]*supplier model allowlist/,
  'Ability-model routing empty state must explain that candidates come from the supplier model allowlist'
);

assert.match(
  abilityModelsSource,
  /speech\|audio\|voice\|tts\|ocr\|vision\|image\|embed[\s\S]*featureTokens\.includes\('text'\)/,
  'Ability-model routing must exclude obvious non-text model ids before accepting text-tagged candidates'
);

assert.match(
  abilityModelsSource,
  /modelSearchQuery[\s\S]*field_model_search[\s\S]*filteredCandidates/,
  'Ability-model routing dialog must provide model search over runtime model candidates'
);

assert.doesNotMatch(
  abilityModelsSource,
  /updateRoutingCandidate\(activeProfile\.profile_id, index, event\.target\.value\)/,
  'Ability-model routing dialog must not rely on the old long native candidate select for choosing models'
);

assert.match(
  abilityModelsSource,
  /advancedRuntimePolicyOpen[\s\S]*advanced_runtime_policy_title[\s\S]*field_timeout_ms[\s\S]*field_allow_fallback[\s\S]*field_retry_max/,
  'Ability-model routing dialog must keep timeout, fallback, retry, and note behind an advanced runtime policy disclosure'
);

assert.match(
  abilityModelsSource,
  /status_unconfigured[\s\S]*status_needs_config[\s\S]*status_ok/,
  'Ability-model routing table status must describe exceptions while normal rows stay quiet'
);

assert.match(
  abilityModelsSource,
  /function renderRouteStatus[\s\S]*routeStatus\.status === 'success'[\s\S]*text-slate-500[\s\S]*BackofficeStatusBadge/,
  'Ability-model routing table must render normal status as quiet text and reserve badges for exceptions'
);

assert.match(
  abilityModelsSource,
  /abilityRoutePolicySummary[\s\S]*policy_auto_fallback_enabled[\s\S]*policy_auto_fallback_disabled/,
  'Ability-model routing table policy summary must describe the visible fallback setting'
);

assert.doesNotMatch(
  abilityModelsSource,
  /abilityRoutePolicySummary[\s\S]*fallbackCount/,
  'Ability-model routing table policy summary must not expose internal candidate counts as fallback counts'
);

assert.match(
  abilityModelsSource,
  /type AbilityModelRouteRow[\s\S]*taskLabels: string\[\]/,
  'Ability-model routing page must model shared route groups instead of treating each task as a separate configuration object'
);

assert.match(
  abilityModelsSource,
  /routingDrafts\.map\(\(profile\)[\s\S]*taskLabels: profile\.tasks\.map\(abilityTaskLabel\)/,
  'Ability-model routing table must render one row per shared routing profile with task chips'
);

assert.doesNotMatch(
  pageSource,
  /BackofficeSummaryStrip/,
  'Provider management page must not use a separate summary strip that increases header height'
);

assert.doesNotMatch(
  aiResourcesPrimaryPanelSource,
  /metrics\.map|badge_runtime_resources|badge_review_boundary|metric_connections|metric_capabilities|metric_profiles|metric_write_posture/,
  'AI resources primary panel must not regress to the old generic runtime badges or metric chips'
);

assert.match(
  pageSource,
  /const \[activeView, setActiveView\] = useState<AIResourceView>\('connections'\)/,
  'AI resources page must default to the supplier workspace'
);

assert.doesNotMatch(
  pageSource,
  /workspaceTabs|role="tab"[\s\S]*tab_overview[\s\S]*tab_connections[\s\S]*tab_diagnostics/,
  'AI resources primary panel must not expose nested overview/supplier/diagnostics workspace tabs'
);

assert.match(
  pageSource,
  /overview_model_suppliers[\s\S]*overview_capability_suppliers[\s\S]*overview_runtime_profiles[\s\S]*overview_telemetry/,
  'AI resources overview must use a compact runtime resource status strip'
);

assert.doesNotMatch(
  pageSource,
  /overview_actions_boundary[\s\S]*routing, prompts, abilities, or WordPress writes/,
  'AI resources page must not keep the old overview action-card boundary copy'
);

assert.match(
  pageSource,
  /href="\/admin\/troubleshooting"[\s\S]*action_view_diagnostics/,
  'AI resources page must route diagnostics through the Runtime Diagnostics page'
);

assert.doesNotMatch(
  pageSource,
  /model_marketplace|model_square|wallet|redeem|ranking|playground|prompt_router_editor|savePrompt|saveRouter/,
  'AI resources must not copy NEW API commercial marketplace or prompt/router control-plane surfaces'
);

assert.doesNotMatch(
  abilityModelsSource,
  /BackofficeSummaryStrip/,
  'Ability-model routing page must not use a separate summary strip after header metrics move into the right-side header summary'
);

assert.match(
  abilityModelsSource,
  /headerSummary[\s\S]*badge_runtime_binding[\s\S]*headerSummary/,
  'Ability-model routing page must keep compact ability, route, and model-candidate counts in the header aside'
);

assert.match(
  abilityModelsSource,
  /abilityScenarioCount[\s\S]*routeCount[\s\S]*modelCandidateCount/,
  'Ability-model routing header summary must combine ability scenarios, route count, and model candidates instead of separate metric chips'
);

assert.match(
  abilityModelsSource,
  /activeAbilityTab === 'wordpress'[\s\S]*wordpress_title/,
  'Plugin ability-model routing must render only under the plugin ability child tab'
);

assert.match(
  abilityModelsSource,
  /activeAbilityTab === 'cloud'[\s\S]*cloud_native_title/,
  'Ability-model routing page must reserve a Cloud-native child tab without creating a second control plane'
);

assert.match(
  abilityModelsSource,
  /fetch\('\/api\/admin\/ability-models\/runtime-projection'/,
  'Cloud-native ability tab must load read-only runtime rows from the backend projection'
);

assert.match(
  abilityModelsSource,
  /normalizeCloudAbilityRuntimeRows[\s\S]*payload\.data/,
  'Cloud-native backend projection must be normalized before rendering'
);

assert.doesNotMatch(
  abilityModelsSource,
  /const cloudNativeAbilityRows = \[/,
  'Cloud-native ability rows must not be hard-coded in the frontend'
);

assert.doesNotMatch(
  abilityModelsSource,
  /id: 'tag_recommendation'|id: 'category_recommendation'|id: 'title_suggestion'|id: 'meta_description'/,
  'Cloud-native ability tab must not duplicate plugin taxonomy, title, or SEO metadata abilities'
);

assert.doesNotMatch(
  abilityModelsSource,
  /cloud_ability_tag_recommendation|cloud_ability_category_recommendation|cloud_ability_title_suggestion|cloud_ability_meta_description/,
  'Cloud-native ability copy must not reintroduce duplicate plugin ability rows'
);

assert.doesNotMatch(
  abilityModelsSource,
  /cloud_ability_content_support|cloud_ability_generated_image_candidates/,
  'Cloud runtime dependencies must not duplicate plugin content support or image generation route rows'
);

assert.match(
  abilityModelsSource,
  /cloud_native_status_connected/,
  'Cloud-native existing abilities must expose a connected status instead of all planned placeholders'
);

assert.match(
  abilityModelsSource,
  /row\.can_configure \?[\s\S]*openCloudBindingDialog\(row\)[\s\S]*cloud_native_action_configure_model[\s\S]*cloudManagedDependencyLabel\(row\)/,
  'Cloud-native runtime projection rows must expose configure only when supported and explain read-only dependencies as managed by their supplier settings'
);

assert.match(
  abilityModelsSource,
  /column_runtime_dependency[\s\S]*column_current_runtime[\s\S]*cloud_native_internal_details/,
  'Cloud-native ability table must show operator-facing dependency/runtime columns and move internal profile ids into collapsed details'
);

assert.match(
  abilityModelsSource,
  /availableCloudMediaTabs[\s\S]*CLOUD_MEDIA_ORDER\.filter\(\(media\) => cloudAbilityRows\.some\(\(row\) => row\.media === media\)\)[\s\S]*activeCloudMediaFilter[\s\S]*cloudAbilityRows\.filter\(\(row\) => row\.media === activeCloudMediaFilter\)/,
  'Cloud runtime dependency category filter must render only categories present in current rows and filter by row media when selected'
);

assert.doesNotMatch(
  abilityModelsSource,
  /\(\['text', 'image', 'vector', 'audio', 'video'\] as CloudAbilityMediaTab\[\]\)\.map/,
  'Cloud runtime dependency category UI must not expose empty audio or video filters from a hard-coded select list'
);

assert.match(
  abilityModelsSource,
  /column_status[\s\S]*<select[\s\S]*field_category_filter[\s\S]*filter_category_all[\s\S]*availableCloudMediaTabs\.map[\s\S]*column_ability[\s\S]*column_category[\s\S]*cloud_media_tab_\$\{row\.media\}/,
  'Cloud runtime dependency table must keep category filtering inside the category column header'
);

assert.doesNotMatch(
  abilityModelsSource,
  /setActiveCloudMediaTab|activeCloudMediaTab/,
  'Cloud-native ability categories must not remain as a top-level media tab state'
);

assert.doesNotMatch(
  abilityModelsSource,
  /grid-cols-\[8rem_1\.4fr_1fr_1\.1fr_1\.2fr_9rem\]|column_model_kind[\s\S]*column_profile[\s\S]*column_provider_model/,
  'Cloud-native ability table must not default-display model-kind/profile/provider technical columns'
);

assert.doesNotMatch(
  abilityModelsSource,
  /activeCloudMediaTab === 'audio' && preferences/,
  'Cloud-native ability media tabs must not hide audio preference writes inside the Cloud-native projection'
);

assert.match(
  abilityModelsSource,
  /abilityModelRows\.map[\s\S]*openAbilityModelDialog\(row\.profile\.profile_id\)[\s\S]*activeProfile[\s\S]*saveAbilityModelProfile/,
  'Audio runtime model routes must be configurable through the same plugin ability routing dialog as other route profiles'
);

assert.doesNotMatch(
  abilityModelsSource,
  /audio_preferences_title[\s\S]*BackofficeSectionPanel/,
  'Audio runtime profile preferences must not remain a separate configurable section after merging the routing table'
);

assert.match(
  abilityModelsSource,
  /cloud_native_badge_runtime_binding/,
  'Cloud-native ability section must present bounded runtime binding instead of planned-only status'
);

assert.match(
  abilityModelsSource,
  /cloudAbilityRows\.length === 0[\s\S]*cloud_all_empty_title[\s\S]*cloud_all_empty_desc/,
  'Cloud-native ability table must keep a clear empty state when the backend projection has no rows'
);

assert.match(
  abilityModelsSource,
  /cloud_native_boundary_notice/,
  'Cloud-native planned ability rows must preserve the no-control-plane boundary notice'
);

assert.doesNotMatch(
  abilityModelsSource,
  /\/api\/admin\/cloud-ability-routing|saveCloudNativeAbility|generateIdempotencyKey\('cloud_ability/,
  'Cloud-native abilities must not introduce a fake Cloud ability routing write path'
);

assert.match(
  abilityModelsSource,
  /\/api\/admin\/ability-models\/runtime-binding[\s\S]*generateIdempotencyKey\('ability_models_runtime_binding'\)/,
  'Site Knowledge embedding model binding must use the bounded runtime-binding endpoint'
);

assert.match(
  abilityModelsSource,
  /available_embedding_instances[\s\S]*cloudBindingDialogRow[\s\S]*available_embedding_instances/,
  'Site Knowledge embedding dialog must source candidates from embedding runtime instances'
);

assert.match(
  abilityModelsSource,
  /cloudBindingDialogRow\.media[\s\S]*cloud_native_internal_details[\s\S]*cloudBindingDialogRow\.profile_id/,
  'Cloud runtime dependency dialog must show category by default and move profile ids into internal details'
);

assert.doesNotMatch(
  abilityModelsSource,
  /\/api\/admin\/plugin-ability-routing|savePluginAbilityOverride|generateIdempotencyKey\('plugin_ability/,
  'Plugin ability defaults must not introduce plugin-specific override persistence before the boundary is defined'
);

assert.match(
  abilityModelsSource,
  /hidden grid-cols-\[7rem_1\.7fr_6rem_1\.45fr_1\.15fr_7rem\][\s\S]*md:grid-cols-\[7rem_1\.7fr_6rem_1\.45fr_1\.15fr_7rem\]/,
  'Unified ability-model routing table must use a desktop grid only at md and a stacked mobile layout below md without a separate internal model-config column'
);

assert.match(
  abilityModelsSource,
  /abilityModelRows/,
  'Ability-model routing page must render WordPress AI connector route groups as ability-model route rows'
);

assert.match(
  abilityModelsSource,
  /saveAbilityModelProfile/,
  'Ability-model routing configuration must save the selected shared runtime profile'
);

assert.match(
  abilityModelsSource,
  /generateIdempotencyKey\('ability_models_routing'\)/,
  'Ability model saves must use backend-safe idempotency keys without unsupported header characters'
);

assert.match(
  abilityModelsSource,
  /dialogError[\s\S]*role="alert"/,
  'Ability model save failures must be visible inside the configuration dialog'
);

assert.match(
  abilityModelsSource,
  /resolveAdminApiPayloadMessage[\s\S]*payload\.message[\s\S]*payload\.detail[\s\S]*payload\.error_code/,
  'Ability model save failures must surface backend validation details instead of a generic fallback'
);

assert.match(
  abilityModelsSource,
  /dialogMessage[\s\S]*role="status"/,
  'Ability model save success must be visible inside the configuration dialog'
);

assert.match(
  abilityModelsSource,
  /setDialogMessage\(aiText\('message_ability_models_saved'/,
  'Ability model save success must use localized UI copy instead of backend English receipt summaries'
);

assert.match(
  abilityModelsSource,
  /abilityModelInstanceDetail[\s\S]*ability_model_instance_detail[\s\S]*abilityModelFeatureLabel[\s\S]*abilityModelRegionLabel[\s\S]*abilityModelHealthLabel/,
  'Ability model instance details must localize runtime feature, region, and health labels while preserving technical ids'
);

assert.match(
  abilityModelsSource,
  /abilityModelRuntimeSummary[\s\S]*ability_model_runtime_summary[\s\S]*abilityModelFeatureLabel[\s\S]*abilityModelRegionLabel[\s\S]*abilityModelHealthLabel/,
  'Ability model dialogs must default-display human runtime summaries without exposing instance ids'
);

assert.match(
  abilityModelsSource,
  /abilityModelRuntimeSummary\(selected\)[\s\S]*<details[\s\S]*abilityModelInstanceDetail\(selected\)[\s\S]*abilityModelRuntimeSummary\(instance\)[\s\S]*<details[\s\S]*abilityModelInstanceDetail\(instance\)/,
  'Ability model dialogs must move instance-level technical ids behind internal details disclosures'
);

assert.match(
  abilityModelsSource,
  /MAX_DIALOG_CANDIDATE_OPTIONS = 24[\s\S]*filteredCandidates[\s\S]*slice\(0, MAX_DIALOG_CANDIDATE_OPTIONS\)/,
  'Ability model dialog must keep default model selectors bounded instead of exposing the entire runtime catalog'
);

assert.match(
  abilityModelsSource,
  /activeProfileTitle[\s\S]*abilityTaskLabel/,
  'Ability model dialog must use localized ability labels instead of raw backend profile labels'
);

assert.match(
  abilityModelsSource,
  /createPortal[\s\S]*document\.body/,
  'Ability model dialog must render through a body portal instead of being trapped below the admin shell'
);

assert.match(
  abilityModelsSource,
  /z-\[2147483647\][\s\S]*absolute inset-0 bg-slate-950\/55/,
  'Ability model dialog overlay must cover the whole admin shell above sticky headers'
);

assert.match(
  abilityModelsSource,
  /Plugin-specific overrides can be added later when a plugin needs a different model/,
  'Ability model configuration must frame plugin-specific overrides as a later bounded enhancement'
);

assert.match(
  abilityModelsSource,
  /plugin_default_notice[\s\S]*Plugin switches, prompts, approvals, and final WordPress writes stay in the local plugin path/,
  'Plugin ability defaults must preserve local plugin prompt, approval, and WordPress write boundaries'
);

assert.match(
  pageSource,
  /action_fetch_upstream_models/,
  'Provider channel form must expose a fetch-from-upstream models action'
);

assert.match(
  pageSource,
  /id: 'deepseek'[\s\S]*baseUrl: 'https:\/\/api\.deepseek\.com\/v1'[\s\S]*deepseek-chat, deepseek-reasoner/,
  'Provider channel presets must include DeepSeek as an OpenAI-compatible text supplier'
);

assert.match(
  pageSource,
  /id: 'deepseek'[\s\S]*websiteUrl: 'https:\/\/www\.deepseek\.com\/'[\s\S]*statusUrl: 'https:\/\/status\.deepseek\.com\/'[\s\S]*docsUrl: 'https:\/\/api-docs\.deepseek\.com\/'/,
  'Provider channel DeepSeek preset must expose official website, status, and docs reference links'
);

assert.match(
  pageSource,
  /id: 'openai_compatible'[\s\S]*websiteUrl: 'https:\/\/openai\.com\/'[\s\S]*statusUrl: 'https:\/\/status\.openai\.com\/'[\s\S]*docsUrl: 'https:\/\/developers\.openai\.com\/api\/docs'/,
  'OpenAI-compatible default preset must expose official OpenAI reference links'
);

assert.match(
  pageSource,
  /id: 'anthropic'[\s\S]*websiteUrl: 'https:\/\/www\.anthropic\.com\/'[\s\S]*statusUrl: 'https:\/\/status\.claude\.com\/'[\s\S]*docsUrl: 'https:\/\/platform\.claude\.com\/docs'/,
  'Anthropic preset must expose official Anthropic reference links'
);

assert.match(
  pageSource,
  /id: 'openrouter'[\s\S]*websiteUrl: 'https:\/\/openrouter\.ai\/'[\s\S]*statusUrl: 'https:\/\/status\.openrouter\.ai\/'[\s\S]*docsUrl: 'https:\/\/openrouter\.ai\/docs'/,
  'OpenRouter preset must expose official OpenRouter reference links'
);

assert.match(
  pageSource,
  /id: 'minimax'[\s\S]*websiteUrl: 'https:\/\/www\.minimax\.io\/'[\s\S]*statusUrl: 'https:\/\/status\.minimax\.io\/'[\s\S]*docsUrl: 'https:\/\/platform\.minimax\.io\/docs'/,
  'MiniMax preset must expose official MiniMax reference links'
);

const minimaxPresetStart = pageSource.indexOf("id: 'minimax'");
const minimaxPresetSource = minimaxPresetStart >= 0
  ? pageSource.slice(minimaxPresetStart, pageSource.indexOf("id: 'custom'", minimaxPresetStart))
  : '';

assert.match(
  minimaxPresetSource,
  /label: 'MiniMax'[\s\S]*capabilityIds: 'text_generation, image_generation, audio_generation, video_generation'[\s\S]*runtimeProfileIds: ''/,
  'MiniMax preset must be a general model supplier and must not bind an audio-only runtime profile'
);

assert.doesNotMatch(
  minimaxPresetSource,
  /capabilityIds: 'audio_generation'|audio\.narration/,
  'MiniMax preset must not regress to an audio-only channel'
);

assert.match(
  pageSource,
  /providerId\.includes\('deepseek'\)[\s\S]*return 'deepseek'/,
  'Provider channel edit form must infer existing DeepSeek connections back to the DeepSeek preset'
);

assert.match(
  pageSource,
  /providerCatalogPreview/,
  'Provider channel form must show upstream model preview state'
);

assert.match(
  pageSource,
  /connection_section_title[\s\S]*model_visibility_title/,
  'Provider channel form must separate connection and model visibility'
);

assert.match(
  pageSource,
  /!\s*providerFormOpen && message[\s\S]*!\s*providerFormOpen && error[\s\S]*role="dialog"[\s\S]*\{message \|\| error \? \([\s\S]*border-b border-slate-200 px-5 py-3/,
  'Provider channel dialog must render operation feedback inside the modal instead of behind the overlay'
);

assert.match(
  pageSource,
  /connectionDetailsOpen[\s\S]*setConnectionDetailsOpen\(true\)[\s\S]*setProviderFormMode\('edit'\)[\s\S]*setConnectionDetailsOpen\(false\)[\s\S]*<details[\s\S]*open=\{connectionDetailsOpen\}[\s\S]*onToggle=\{\(event\) => setConnectionDetailsOpen\(event\.currentTarget\.open\)\}/,
  'Provider channel connection fields must be explicitly open for new channels and collapsed by default while editing'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.connection_section_toggle_hint': '低频设置'[\s\S]*'admin\.ai_resources\.connection_summary_base_url_missing': '未填写基础 URL'/,
  'Provider channel collapsed connection summary must provide Simplified Chinese copy'
);

assert.match(
  pageSource,
  /isCapabilityProviderDescriptor[\s\S]*const isCapabilityProviderForm/,
  'Provider channel form must classify capability suppliers before rendering provider-specific fields'
);

assert.match(
  pageSource,
  /providerDialogTitle = providerFormMode === 'edit'[\s\S]*isCapabilityProviderForm[\s\S]*capability_channel_form_edit_named_title[\s\S]*channel_form_edit_named_title/,
  'Capability supplier edit dialog must not reuse the model provider channel title'
);

assert.match(
  pageSource,
  /isCapabilityProviderForm \? null : \([\s\S]*model_visibility_title/,
  'Capability supplier dialog must not render model visibility, model catalog sync, or model reference controls'
);

assert.match(
  pageSource,
  /capability_supplier_badge[\s\S]*capabilityCategoryLabel\(providerFormCapabilityCategory\)/,
  'Capability supplier dialog must show the supplier category as a compact badge instead of a separate usage summary section'
);

assert.doesNotMatch(
  pageSource,
  /capability_usage_summary_title|usageScopeCapabilityLabels|usageScopeProfileLabels/,
  'Capability supplier dialog must not render a separate usage summary section'
);

assert.match(
  pageSource,
  /capability_diagnostics_title[\s\S]*field_base_url[\s\S]*field_capabilities[\s\S]*field_profiles[\s\S]*field_connection_id[\s\S]*field_provider_id[\s\S]*field_kind[\s\S]*field_source_role/,
  'Capability supplier internal IDs and usage scope must stay folded under technical information'
);

assert.doesNotMatch(
  capabilityDiagnosticsSource,
  /<input|<select|onChange=/,
  'Capability supplier technical information must be read-only and must not expose internal edit controls'
);

assert.match(
  pageSource,
  /shouldLockCapabilityBaseUrl[\s\S]*readOnly=\{shouldLockCapabilityBaseUrl\}/,
  'Known capability supplier base URLs must be read-only in the default connection section'
);

assert.match(
  pageSource,
  /!isCapabilityProviderForm \? \([\s\S]*PROVIDER_PRESETS\.map/,
  'Model provider presets must not render for capability supplier dialogs'
);

assert.doesNotMatch(
  pageSource,
  /field_capability_supplier_type/,
  'Capability supplier type must stay as a compact badge instead of a default form field'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.capability_channel_form_edit_title': '编辑能力供应商'/,
  'Capability supplier dialog must provide Simplified Chinese copy distinct from model provider channels'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.capability_diagnostics_title': '技术信息'/,
  'Capability supplier diagnostics disclosure must provide Simplified Chinese copy'
);

assert.match(
  pageSource,
  /max-h-\[calc\(100vh-3rem\)\][\s\S]*flex min-h-0 flex-1 flex-col[\s\S]*overflow-y-auto[\s\S]*save_test_notice/,
  'Provider channel dialog must keep the modal bounded with internal scrolling and a visible save footer'
);

assert.match(
  pageSource,
  /aria-label=\{aiText\('action_close_dialog'[\s\S]*<span aria-hidden="true">X<\/span>[\s\S]*action_cancel/,
  'Provider channel dialog must demote the top close action to a small icon while keeping the footer cancel action'
);

assert.doesNotMatch(
  pageSource,
  /model_visibility_desc/,
  'Provider channel dialog should not repeat capability-model routing explanation inside the compact modal'
);

assert.match(
  pageSource,
  /capability_diagnostics_desc[\s\S]*Read-only runtime metadata for support and migration/,
  'Capability supplier technical information copy must frame internal bindings as read-only metadata'
);

assert.match(
  pageSource,
  /providerUsesCustomRuntimeFields \? \([\s\S]*advanced_settings_title[\s\S]*field_connection_id[\s\S]*field_provider_id[\s\S]*field_kind[\s\S]*field_source_role[\s\S]*field_capabilities[\s\S]*field_profiles/,
  'Provider channel runtime identity and usage scope fields must stay hidden unless the operator is configuring a custom channel'
);

assert.match(
  pageSource,
  /verifiedModelIds[\s\S]*runtime_supported[\s\S]*setProviderModelIds\(verifiedModelIds\)/,
  'Provider channel catalog sync must only auto-enable runtime verified models'
);

assert.match(
  pageSource,
  /modelReferenceFeatureFilter[\s\S]*field_feature_filter[\s\S]*catalog_model_status_verified/,
  'Provider channel merged model list must expose feature filtering and upstream verification status'
);

assert.match(
  i18nSource,
  /admin\.ai_resources\.ability_model_feature_text_generation': '文本生成'[\s\S]*admin\.ai_resources\.ability_model_feature_image_generation': '图片生成'[\s\S]*admin\.ai_resources\.ability_model_feature_audio_generation': '音频生成'[\s\S]*admin\.ai_resources\.ability_model_feature_video_generation': '视频生成'[\s\S]*admin\.ai_resources\.ability_model_feature_embedding': '向量嵌入'/,
  'Provider channel model feature labels must have Chinese translations instead of falling back to English'
);

assert.match(
  pageSource,
  /modelIds:\s*\(connection\.model_ids \|\| \[\]\)\.join/,
  'Provider channel edit form must restore saved model ids from the backend projection'
);

assert.doesNotMatch(
  pageSource,
  /enabled_models_title|action_remove_model_named/,
  'Provider channel form should avoid duplicate selected-model chip panels above the catalog list'
);

assert.match(
  pageSource,
  /action_fetch_upstream_models[\s\S]*action_sync_model_references[\s\S]*action_clear_all_models/,
  'Provider channel form must make catalog sync the combined primary action while keeping reference-only retry and clear-all secondary'
);

assert.match(
  pageSource,
  /modelReferenceShowDeprecated[\s\S]*useState\(false\)[\s\S]*deprecatedEnableBlocked[\s\S]*action_enable_deprecated_model_blocked/,
  'Provider channel form must hide deprecated models by default and block newly enabling them'
);

assert.match(
  pageSource,
  /customModelInput/,
  'Provider channel form must support adding specified models after clearing upstream selections'
);

assert.doesNotMatch(
  pageSource,
  /action_fill_related_models|action_fill_all_models|action_copy_all_models/,
  'Provider channel form should avoid low-frequency bulk helpers beyond upstream fetch, clear all, and specified add'
);

assert.doesNotMatch(
  pageSource,
  /batch_test_models|action_test_all_models|model_batch_test|Test all models/,
  'Provider channel form must not introduce model batch testing in this phase'
);

assert.match(
  pageSource,
  /model-references\?\$\{params\.toString\(\)\}/,
  'Provider channel form must load model reference intelligence by provider'
);

assert.match(
  pageSource,
  /model-references\/sync/,
  'Provider channel form must expose a bounded reference intelligence sync action'
);

assert.match(
  pageSource,
  /formatReferencePrice[\s\S]*price_unit_per_1m/,
  'Provider channel model reference rows must keep reference prices explicitly labeled as reference-only metadata'
);

assert.match(
  pageSource,
  /formatReferenceContext[\s\S]*model_reference_missing_context[\s\S]*formatReferencePrice[\s\S]*model_reference_missing_price/,
  'Provider channel model reference rows must explain missing context and price reference data instead of showing bare dashes'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.model_reference_missing_context': '暂无情报'[\s\S]*'admin\.ai_resources\.model_reference_missing_price': '暂无参考价'/,
  'Provider channel missing model reference copy must be localized in Simplified Chinese'
);

assert.match(
  pageSource,
  /column_reference_price[\s\S]*price_unit_per_1m[\s\S]*formatReferencePrice/,
  'Provider channel reference table must label price units in the header instead of repeating them in every row'
);

assert.match(
  pageSource,
  /modelVisibilityRows/,
  'Provider channel form must merge upstream catalog and reference intelligence into one model list'
);

assert.doesNotMatch(
  `${pageSource}\n${i18nSource}`,
  /catalog_preview_truncated|前 100|first 100|only display/i,
  'Provider channel model catalog must not present upstream models as a 100-item truncated preview'
);

assert.match(
  pageSource,
  /field_reference_provider/,
  'Provider channel form must allow choosing a reference provider for compatible or custom channels'
);

assert.match(
  pageSource,
  /canChooseReferenceProvider[\s\S]*openai_compatible[\s\S]*newapi[\s\S]*custom[\s\S]*referenceProviderCanBeChanged \? \([\s\S]*<details/,
  'Provider channel form must hide reference provider selection by default and expose it only as advanced detail for compatible or custom channels'
);

assert.match(
  pageSource,
  /field_search_models[\s\S]*model_visibility_more_operations[\s\S]*field_show_deprecated_models[\s\S]*sticky top-0[\s\S]*field_visibility_filter[\s\S]*catalog_model_header_model[\s\S]*field_feature_filter/,
  'Provider channel model list must keep search above the table and move column filters into sticky headers'
);

assert.match(
  pageSource,
  /lg:grid-cols-\[minmax\(0,1fr\)_minmax\(18rem,0\.8fr\)\][\s\S]*model_visibility_operations_title[\s\S]*model_visibility_status_title[\s\S]*manual_model_add_title[\s\S]*manual_model_add_desc/,
  'Provider channel low-frequency model tools must separate actions, status, and manual model add'
);

assert.doesNotMatch(
  pageSource,
  /xl:grid-cols-\[minmax\(16rem,1fr\)_10rem_10rem_auto_auto\]/,
  'Provider channel model toolbar must not keep a separate feature filter before the table'
);

assert.doesNotMatch(
  pageSource,
  /model_visibility_result_count/,
  'Provider channel model list must not duplicate the enabled/available summary as a second result count'
);

assert.match(
  pageSource,
  /field_visibility_filter[\s\S]*catalog_model_header_model[\s\S]*aria-pressed=\{row\.selected\}[\s\S]*status_model_enabled[\s\S]*status_model_disabled/,
  'Provider channel model rows must combine visibility status and enable-disable action into one visibility control'
);

assert.match(
  pageSource,
  /sourceKind: 'manual'[\s\S]*const canRemoveManualModel = row\.sourceKind === 'manual' && row\.selected[\s\S]*removeProviderModelId\(row\.modelId\)[\s\S]*action_remove_manual_model/,
  'Provider channel manually added saved-ID rows must expose an explicit remove action'
);

assert.doesNotMatch(
  pageSource,
  /catalog_model_header_action/,
  'Provider channel model rows must not keep a separate action column for the same visibility state'
);

assert.match(
  pageSource,
  /normalizeModelReferenceFeature[\s\S]*return 'all'[\s\S]*family: aiText\('model_source_manual'[\s\S]*feature: ''/,
  'Provider channel manually restored models must not be forced into text generation when no model intelligence exists'
);

assert.match(
  pageSource,
  /model_catalog_preview: isCapabilityProviderForm[\s\S]*catalogPreviewForMetadata\(providerCatalogPreview\)[\s\S]*catalogPreviewFromConnection\(connection\)/,
  'Provider channel saves a sanitized upstream catalog preview and restores it when editing the connection'
);

assert.match(
  pageSource,
  /const referenceLinks = providerReferenceLinksForForm\(providerConnectionForm\)[\s\S]*website_url: websiteUrl \|\| undefined[\s\S]*status_url: statusUrl \|\| undefined[\s\S]*docs_url: docsUrl \|\| undefined/,
  'Provider channel save payload must persist only preset reference links as provider metadata'
);

assert.match(
  pageSource,
  /provider_links_title[\s\S]*providerFormExternalLinkItems\.map[\s\S]*href=\{item\.href\}/,
  'Provider channel form must render preset reference links as read-only actions'
);

assert.doesNotMatch(
  pageSource,
  /field_provider_website_url|field_provider_status_url|field_provider_docs_url|providerConnectionForm\.websiteUrl|providerConnectionForm\.statusUrl|providerConnectionForm\.docsUrl/,
  'Provider channel form must not ask operators to type official website, status, or docs URLs'
);

assert.match(
  pageSource,
  /connectionExternalLinkItems\(connection\)[\s\S]*providerLinkItems\.map[\s\S]*href=\{item\.href\}/,
  'Provider channel list must render provider reference links without mixing them into model rows'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.provider_links_title': '参考入口'[\s\S]*'admin\.ai_resources\.provider_link_website': '官网'[\s\S]*'admin\.ai_resources\.provider_link_status': '状态'[\s\S]*'admin\.ai_resources\.provider_link_docs': '文档'/,
  'Provider channel reference link labels must be localized in Simplified Chinese'
);

assert.match(
  pageSource,
  /modelLookupKeys[\s\S]*selectedModelIdFor[\s\S]*hasModelMetadataFor[\s\S]*model_metadata_gap_hint/,
  'Provider channel model rows must match provider-prefixed model IDs and explain saved-ID-only metadata gaps'
);

assert.match(
  pageSource,
  /inferReferenceProviderFromModelIds[\s\S]*modelProviderPrefix[\s\S]*referenceProviderForConnection[\s\S]*setModelReferenceProviderId\(referenceProviderForConnection\(connection\)\)/,
  'Provider channel must infer models.dev reference provider from provider-prefixed model ids such as deepseek/model-name'
);

assert.match(
  pageSource,
  /modelReferenceStatusText[\s\S]*model_reference_status_loaded[\s\S]*model_reference_status_not_synced[\s\S]*modelReferenceStatusText/,
  'Provider channel must show models.dev reference intelligence sync status beside model visibility'
);

assert.match(
  pageSource,
  /autoSyncedReferenceProviders[\s\S]*modelReferenceSourceNeedsSync[\s\S]*autoSyncModelReferences/,
  'Provider channel must automatically sync missing models.dev reference intelligence once per provider'
);

assert.match(
  autoSyncModelReferencesSource,
  /catch \(syncError\)[\s\S]*setModelReferenceAutoSyncError/,
  'Automatic models.dev sync failures must stay local to the model reference panel'
);

assert.doesNotMatch(
  autoSyncModelReferencesSource,
  /catch \(syncError\)[\s\S]*setError/,
  'Automatic models.dev sync failures must not raise a page-level global error'
);

assert.match(
  pageSource,
  /disabled=\{syncingModelReferences \|\| autoSyncingModelReferences \|\| loadingModelReferences \|\| savingConnection\}/,
  'Provider channel reference sync action must be disabled while automatic models.dev sync is running'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.model_metadata_gap_hint': '[^']*只有已保存 ID[^']*'/,
  'Provider channel metadata gap hint must be localized in Simplified Chinese'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.model_reference_status_auto_syncing': '[^']*自动同步 models\.dev[^']*'[\s\S]*'admin\.ai_resources\.model_reference_status_auto_sync_failed': '[^']*自动同步失败[^']*'[\s\S]*'admin\.ai_resources\.model_reference_status_loaded': '[^']*models\.dev[^']*'[\s\S]*'admin\.ai_resources\.model_reference_status_not_synced': '[^']*尚未同步[^']*'/,
  'Provider channel models.dev reference status copy must be localized in Simplified Chinese'
);

assert.doesNotMatch(
  pageSource,
  /model_visibility_list_title|modelVisibilityRows\.length \? \([\s\S]*max-h-80 overflow-auto rounded-lg border/,
  'Provider channel model list must avoid duplicate list headers and nested card borders around the table'
);

assert.match(
  pageSource,
  /PROVIDER_PRESETS/,
  'AI resources provider form must expose provider presets instead of requiring raw identifiers first'
);

assert.match(
  pageSource,
  /Add provider channel/,
  'AI resources provider form must be framed as adding a provider channel'
);

assert.match(
  pageSource,
  /providerFormOpen/,
  'AI resources provider form must stay hidden until the operator opens it'
);

assert.match(
  pageSource,
  /function closeProviderForm\(\)[\s\S]*setProviderFormOpen\(false\)[\s\S]*setMessage\(''\)[\s\S]*setError\(''\)/,
  'Closing the provider form must clear transient edit/cancel messages before returning to the supplier page'
);

assert.equal(
  (pageSource.match(/onClick=\{closeProviderForm\}/g) || []).length,
  2,
  'Provider form close and cancel actions must use the transient-message cleanup path'
);

assert.match(
  pageSource,
  /role="dialog"/,
  'AI resources provider form must open as an explicit dialog'
);

assert.match(
  pageSource,
  /action_view_diagnostics/,
  'AI resources primary panel must expose diagnostics as the page-level action'
);

assert.doesNotMatch(
  aiResourcesPrimaryPanelSource,
  /action_add_model_supplier|action_add_capability_supplier/,
  'AI resources primary panel must not duplicate supplier add actions'
);

assert.match(
  connectionsToolbarSource,
  /field_supplier_type_filter[\s\S]*role="tablist"[\s\S]*supplier_filter_model[\s\S]*supplier_filter_capability[\s\S]*field_search_connections[\s\S]*action_add_model_supplier[\s\S]*action_add_capability_supplier/,
  'Supplier type tabs and add actions must live in the top supplier toolbar'
);

assert.doesNotMatch(
  connectionsToolbarSource,
  /supplier_tab_model[\s\S]*supplier_tab_capability/,
  'AI resources connections view must not keep model/capability suppliers as nested tabs'
);

assert.doesNotMatch(
  pageSource,
  /ai_suppliers_desc/,
  'Model supplier list must not keep redundant inner helper copy'
);

assert.match(
  pageSource,
  /column_enabled_models/,
  'Model supplier list must expose enabled model count as the main model column'
);

assert.match(
  pageSource,
  /column_enabled_models', 'Runtime allowlist'[\s\S]*model_catalog_allowlist_short_hint/,
  'Model supplier list must label enabled models as the runtime allowlist used by ability routes'
);

assert.match(
  pageSource,
  /model_visibility_allowlist_desc[\s\S]*Only enabled models[\s\S]*ability-model routing/,
  'Provider channel form must state that selected models are the runtime allowlist'
);

assert.match(
  pageSource,
  /filter_all_statuses[\s\S]*column_provider[\s\S]*column_enabled_models[\s\S]*model_catalog_enabled_count_short[\s\S]*model_catalog_none_enabled_short/,
  'Model supplier list must use explicit all-status filtering and compact enabled model counts'
);

assert.doesNotMatch(
  pageSource,
  /column_enabled_models[\s\S]*model_catalog_enabled_count'[\s\S]*model_catalog_none_enabled'/,
  'Model supplier enabled-model rows must not repeat full enabled-model sentence copy'
);

assert.doesNotMatch(
  pageSource,
  /column_base_url[\s\S]*model_catalog_enabled_count_short|modelSample/,
  'Model supplier list must keep base URL and model-name previews out of the main table'
);

assert.doesNotMatch(
  pageSource,
  /column_capabilities_profiles/,
  'Model supplier list must not foreground capability/profile scope as a main table column'
);

assert.match(
  pageSource,
  /connectionSearch/,
  'AI resources provider channel list must support search'
);

assert.match(
  pageSource,
  /connectionStatusFilter/,
  'AI resources provider channel list must support status filtering'
);

assert.doesNotMatch(
  pageSource,
  /SupplierSettingsTab/,
  'Provider management must use a supplier type filter instead of operator tabs'
);

assert.match(
  pageSource,
  /SupplierTypeFilter[\s\S]*supplierTypeFilter/,
  'Provider management must keep model and capability suppliers as a single filtered supplier workspace'
);

assert.match(
  pageSource,
  /CapabilityProviderCategory/,
  'Capability supplier management must model search, image, and vector categories explicitly'
);

assert.match(
  pageSource,
  /capabilityProviderCategory/,
  'Capability supplier rows must be classified before display'
);

assert.match(
  pageSource,
  /capabilityConnectionsByCategory/,
  'Capability suppliers must be grouped by category for operator scanning'
);

assert.match(
  pageSource,
  /CAPABILITY_PROVIDER_TEMPLATES/,
  'Capability supplier add flow must use built-in provider templates'
);

assert.match(
  pageSource,
  /capabilityAddDialogOpen/,
  'Capability supplier add flow must open an explicit template dialog'
);

assert.match(
  pageSource,
  /role="tablist"[\s\S]*capability_add_category_tabs[\s\S]*role="tab"/,
  'Capability supplier add dialog must separate built-in templates by category tabs'
);

assert.match(
  pageSource,
  /visibleCapabilityTemplates[\s\S]*capability_add_active_category_count/,
  'Capability supplier add dialog must render only the active category template list'
);

assert.match(
  pageSource,
  /openCapabilityProviderTemplate/,
  'Choosing a capability supplier template must route to provider configuration'
);

assert.match(
  pageSource,
  /setProviderConnectionForm\(\{/,
  'Capability supplier templates must prefill the DB-managed provider connection form'
);

assert.match(
  pageSource,
  /kind: template\.kind/,
  'Capability supplier templates must preserve provider kind for runtime DB projection'
);

assert.doesNotMatch(
  pageSource,
  /activeCapabilityProviderTemplate/,
  'Capability supplier configuration must not use the old env-backed provider settings dialog'
);

assert.match(
  pageSource,
  /id: 'apify'/,
  'Capability supplier templates must include Apify as a built-in search supplier'
);

assert.match(
  pageSource,
  /id: 'zhihu'/,
  'Capability supplier templates must include Zhihu as a built-in search supplier'
);

assert.doesNotMatch(
  pageSource,
  /label: 'TEI Embedding'/,
  'Capability supplier templates must not default-expose embedding model providers as capability suppliers'
);

assert.doesNotMatch(
  pageSource,
  /label: 'OpenAI Embedding'/,
  'Capability supplier templates must not default-expose model-platform embedding as a separate capability supplier'
);

assert.doesNotMatch(
  pageSource,
  /label: 'SiliconFlow Embedding'/,
  'Capability supplier templates must not duplicate SiliconFlow from model suppliers as a separate embedding capability supplier'
);

assert.match(
  pageSource,
  /id: 'siliconflow'[\s\S]*label: 'SiliconFlow'[\s\S]*kind: 'siliconflow'[\s\S]*capabilityIds: 'text_generation, embedding'/,
  'SiliconFlow must stay represented as a model supplier with embedding capability metadata'
);

assert.doesNotMatch(
  openCapabilityTemplateSource,
  /fetch|provider-connections/,
  'Capability supplier add flow must not create dynamic provider connection rows'
);

assert.doesNotMatch(
  pageSource,
  /activeCapabilityPanel === 'search'/,
  'Web-search provider configuration must not open the whole search provider panel from the list'
);

assert.doesNotMatch(
  pageSource,
  /activeCapabilityPanel === 'image'/,
  'Image-source provider configuration must not open the whole image provider panel from the list'
);

assert.doesNotMatch(
  pageSource,
  /activeCapabilityPanel === 'vector'/,
  'Vector suppliers must not render a duplicate category-specific panel below the unified capability supplier list'
);

assert.match(
  pageSource,
  /vector_store_provider/,
  'Provider management must support vector store provider connections'
);

assert.match(
  pageSource,
  /rerank_provider/,
  'Provider management must support rerank provider connections'
);

assert.doesNotMatch(
  pageSource,
  /WebSearchProviderSettings|ImageSourceProviderSettings/,
  'Capability suppliers must use DB-managed provider connections instead of env-backed settings components'
);

assert.doesNotMatch(
  layoutSource,
  /\/admin\/web-search|\/admin\/image-sources/,
  'Old capability provider pages must not remain admin navigation targets'
);

assert.doesNotMatch(
  troubleshootingSource,
  /href: '\/admin\/web-search'|href: '\/admin\/image-sources'/,
  'Advanced Troubleshooting must not link to retired capability provider pages'
);

assert.equal(
  existsSync(webSearchPagePath),
  false,
  'Web Search settings page must be removed after moving into Provider Management'
);

assert.equal(
  existsSync(imageSourcesPagePath),
  false,
  'Image Sources settings page must be removed after moving into Provider Management'
);

assert.doesNotMatch(
  pageSource,
  /\/api\/admin\/web-search-providers|\/api\/admin\/image-source-providers/,
  'Provider Management must not call retired env-backed capability provider APIs'
);

assert.match(
  pageSource,
  /supplierCategory/,
  'AI resources provider channel list must distinguish AI suppliers from capability suppliers'
);

assert.match(
  pageSource,
  /aiSupplierConnections/,
  'AI resources provider channel list must render AI suppliers separately'
);

assert.match(
  pageSource,
  /capabilitySupplierConnections/,
  'AI resources provider channel list must render capability suppliers separately'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.capability_category_filter': '能力分类'/,
  'Capability supplier category filter must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.capability_category_search': '搜索'/,
  'Capability supplier search category must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.capability_category_image': '图片'/,
  'Capability supplier image category must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.capability_category_vector': '向量'/,
  'Capability supplier vector category must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /capability_provider_purpose_search[\s\S]*capability_provider_purpose_image[\s\S]*capability_provider_purpose_rerank[\s\S]*capability_provider_purpose_vector_store/,
  'Capability supplier purpose labels must provide Simplified Chinese copy instead of exposing endpoints in the list'
);

assert.match(
  i18nSource,
  /action_add_credential_channel[\s\S]*message_creating_credential_channel[\s\S]*field_channel_priority[\s\S]*field_channel_note/,
  'Capability supplier priority and channel note controls must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.action_add_capability_supplier': '添加能力供应商'/,
  'Capability supplier add action must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.capability_add_dialog_desc': '已存在的供应商不会重复新增/,
  'Capability supplier add dialog must explain built-in suppliers are not duplicated'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.capability_add_category_tabs': '能力供应商分类'[\s\S]*'admin\.ai_resources\.capability_add_active_category_count': '\{\{count\}\} 个模板'/,
  'Capability supplier add dialog tab labels must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.message_capability_provider_template_existing': '\{\{name\}\} 已存在/,
  'Capability supplier template selection must explain it opens existing configuration'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.web_search_title': '搜索供应商'/,
  'Moved web-search settings must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.image_source_title': '图片供应商'/,
  'Moved image-source settings must provide Simplified Chinese copy'
);

assert.match(
  i18nSource,
  /'admin\.ai_resources\.kind_rerank_provider': '重排提供商'/,
  'Capability supplier vector detail must translate rerank providers'
);

assert.match(
  pageSource,
  /deleteProviderConnection[\s\S]*\/api\/admin\/provider-connections\/\$\{encodeURIComponent\(connection\.connection_id\)\}[\s\S]*method: 'DELETE'/,
  'AI resources provider connection rows must call the bounded provider-connection delete endpoint'
);

assert.match(
  capabilitySupplierTableSource,
  /connection\.managed_by === 'cloud_provider_connections'[\s\S]*setConfirmingDeleteConnectionId\(connection\.connection_id\)[\s\S]*action_delete/,
  'Capability supplier rows must expose delete only for DB-managed provider connections and enter inline confirmation first'
);

assert.doesNotMatch(
  pageSource,
  /window\.confirm[\s\S]*confirm_delete_connection/,
  'Provider connection delete must not use browser-native confirmation dialogs'
);

assert.match(
  pageSource,
  /confirmingDeleteConnectionId[\s\S]*isConfirmingDelete[\s\S]*action_confirm_delete[\s\S]*deleteProviderConnection\(connection\)[\s\S]*action_cancel/,
  'Provider connection delete must require an inline second confirmation with a cancel action'
);

assert.match(
  pageSource,
  /w-44 px-4 py-3 text-center[\s\S]*column_actions[\s\S]*w-44 px-4 py-4 text-center/,
  'Model supplier action column must center its header and row actions'
);

assert.match(
  capabilitySupplierTableSource,
  /w-52 px-4 py-3 text-center[\s\S]*column_actions[\s\S]*w-52 px-4 py-4 text-center align-middle/,
  'Capability supplier action column must center its header and row actions'
);

assert.match(
  pageSource,
  /action_open_config/,
  'AI resources capability supplier rows must use a distinct open-config action'
);

assert.match(
  pageSource,
  /resourceStatusLabel/,
  'AI resources provider channel list must translate raw runtime statuses for operators'
);

assert.match(
  pageSource,
  /providerKindLabel/,
  'AI resources provider channel list must translate provider kinds for operators'
);

assert.match(
  pageSource,
  /<table className="min-w-\[760px\]/,
  'AI resources model suppliers must render as a compact table instead of wide cards or duplicated panels'
);

assert.match(
  pageSource,
  /renderConnectionIssue[\s\S]*connection\.enabled && connection\.configured[\s\S]*return null[\s\S]*provider_issue_runtime_disabled[\s\S]*provider_issue_missing_credential/,
  'AI resources provider channel table must hide normal enabled/configured state and reserve row text for problems'
);

assert.match(
  pageSource,
  /QUIET_STATUS_BADGE_CLASS[\s\S]*connection\.status === 'ready'/,
  'AI resources provider channel table must keep ready statuses visually quiet'
);

assert.doesNotMatch(
  pageSource,
  /data\.env_migration && data\.env_migration\.importable_source_count > 0/,
  'AI resources page must not keep env migration as an operator workflow'
);

assert.doesNotMatch(
  pageSource,
  /<BackofficeStackCard key=\{connection\.connection_id\}/,
  'AI resources provider channels must not regress to repeated large cards'
);

assert.match(
  pageSource,
  /Save and test provider/,
  'AI resources provider form must save and test in one primary action'
);

assert.match(
  pageSource,
  /Advanced runtime settings/,
  'AI resources provider form must keep raw runtime fields behind an advanced disclosure'
);

assert.match(
  pageSource,
  /runProviderConnectionTest\(savedConnectionId/,
  'AI resources provider save must automatically test the saved provider connection'
);

assert.match(
  pageSource,
  /model_ids: modelIds/,
  'AI resources provider form must preserve manually entered model ids as runtime metadata'
);

assert.match(
  pageSource,
  /provider-connections\/.*\/test/,
  'AI resources page must test managed provider connections through the bounded admin endpoint'
);

assert.doesNotMatch(
  pageSource,
  /provider-connections\/import-env/,
  'AI resources page must not expose env provider import after DB-managed provider migration'
);

assert.doesNotMatch(
  pageSource,
  /Provider connections can be managed in Cloud runtime storage/,
  'AI resources page should not render a redundant hero-level boundary explainer card'
);

assert.doesNotMatch(
  pageSource,
  /WordPress writes, approvals, abilities, workflows, prompts, and router truth stay outside this page/,
  'AI resources page should keep boundary copy scoped to relevant detail sections instead of a large hero card'
);

assert.doesNotMatch(
  pageSource,
  /\/admin\/audio-workbench/,
  'AI resources page should not place an unrelated audio workbench CTA in the primary supplier management header'
);

assert.doesNotMatch(
  pageSource,
  /Recent runtime evidence/,
  'AI resources page must not expose recent runtime evidence after it moves to Runtime Diagnostics'
);

assert.match(
  troubleshootingSource,
  /recent_runtime_evidence_title[\s\S]*Recent run metadata/,
  'Runtime Diagnostics must expose recent runtime evidence for operator debugging'
);

assert.match(
  troubleshootingSource,
  /capability_matrix_title[\s\S]*capability_matrix_desc/,
  'Runtime Diagnostics must own the capability-to-provider-model evidence entry'
);

assert.match(
  troubleshootingSource,
  /runtime_resolution_title[\s\S]*Read-only, not a router editor/,
  'Runtime Diagnostics must own the current runtime resolution entry'
);

assert.doesNotMatch(
  pageSource,
  /Feature usage/,
  'AI resources page must not expose feature-to-model usage as an in-page diagnostics panel'
);

assert.doesNotMatch(
  pageSource,
  /Model health/,
  'AI resources page must not expose provider-model health diagnostics as an in-page panel'
);

assert.doesNotMatch(
  pageSource,
  /Last 24h/,
  'AI resources page must not expose model-health diagnostic windows'
);

assert.doesNotMatch(
  pageSource,
  /Last 7d/,
  'AI resources page must not expose model-health diagnostic windows'
);

assert.doesNotMatch(
  pageSource,
  /Feature-to-model evidence from Cloud runtime metadata/,
  'AI resources page must not expose feature usage diagnostic detail'
);

assert.doesNotMatch(
  pageSource,
  /does not change routing, prompts, abilities, or WordPress writes/,
  'AI resources page must not keep copied runtime diagnostics boundary copy'
);

assert.doesNotMatch(
  pageSource,
  /Provider\/model health from provider_call_records/,
  'AI resources page must not expose provider-model health detail'
);

assert.doesNotMatch(
  pageSource,
  /Metadata only: prompts, results, and provider secrets are not exposed/,
  'AI resources page must not expose model-health diagnostic copy'
);

assert.doesNotMatch(
  pageSource,
  /Health alerts are diagnostic only and do not change routing, prompts, abilities, or WordPress writes/,
  'AI resources page must not keep model-health diagnostic detail'
);

assert.doesNotMatch(
  pageSource,
  /read-only diagnostics/,
  'AI resources page must not keep diagnostic-window detail copy'
);

assert.match(
  troubleshootingSource,
  /Read-only, not a router editor/,
  'Runtime Diagnostics runtime resolution must not present itself as a router editor'
);

assert.doesNotMatch(
  pageSource,
  /read-only operator evidence, not a router editor/,
  'AI resources page must not keep runtime-resolution diagnostic copy'
);

assert.doesNotMatch(
  pageSource,
  /Environment migration/,
  'AI resources page must not keep environment-to-DB migration UI after import is complete'
);

assert.doesNotMatch(
  pageSource,
  /Environment values remain fallback only/,
  'AI resources page must not teach operators to manage AI channels through environment fallback'
);

assert.doesNotMatch(
  pageSource,
  /Cloud runtime mapping from capability to profile, provider, model, and write posture/,
  'AI resources page must not keep the runtime mapping matrix explanation'
);

assert.match(
  troubleshootingSource,
  /Current Cloud runtime mapping across capabilities, selected providers, and write posture/,
  'Runtime Diagnostics matrix entry must explain the runtime mapping purpose'
);

assert.doesNotMatch(
  pageSource,
  /not a WordPress ability editor/,
  'AI resources page must not keep matrix copy that belongs to Runtime Diagnostics'
);

assert.match(
  pageSource,
  /field_enabled/,
  'AI resources connections view must expose provider enabled state'
);

assert.match(
  pageSource,
  /status_configured_label[\s\S]*status_missing_secret_label/,
  'AI resources connections view must expose masked provider configured state'
);

assert.match(
  pageSource,
  /last_test/,
  'AI resources connections view must expose masked provider test diagnostics'
);

assert.match(
  pageSource,
  /setProviderFormOpen\(true\)/,
  'AI resources edit action must open the provider form dialog'
);

assert.match(
  pageSource,
  /Credential is left blank unless you replace it/,
  'AI resources edit action must explain masked credential behavior'
);

assert.doesNotMatch(
  pageSource,
  /Prompt and result content are not exposed here/,
  'AI resources page must not keep runtime evidence detail copy'
);

assert.match(
  troubleshootingSource,
  /Recent run metadata used for diagnostics without exposing prompts, results, or provider secrets/,
  'Runtime Diagnostics runtime evidence must be metadata-only'
);

assert.doesNotMatch(
  pageSource,
  /secret:\s*string/,
  'AI resources page must not model raw provider secrets'
);

assert.doesNotMatch(
  pageSource,
  /api_key|group_id/,
  'AI resources page must not expose provider credential fields'
);

assert.doesNotMatch(
  pageSource,
  /auto[- ]?apply|auto[- ]?switch|switch model/i,
  'AI resources page must not expose automatic model routing controls'
);

console.log('admin_ai_resources_contract: ok');
