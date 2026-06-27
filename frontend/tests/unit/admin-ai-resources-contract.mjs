import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const pagePath = resolve(process.cwd(), 'src/app/admin/ai-resources/page.tsx');
const abilityModelsPath = resolve(process.cwd(), 'src/app/admin/ability-models/page.tsx');
const layoutPath = resolve(process.cwd(), 'src/app/admin/layout.tsx');
const troubleshootingPath = resolve(process.cwd(), 'src/app/admin/troubleshooting/page.tsx');
const webSearchPagePath = resolve(process.cwd(), 'src/app/admin/web-search/page.tsx');
const imageSourcesPagePath = resolve(process.cwd(), 'src/app/admin/image-sources/page.tsx');
const pageSource = readFileSync(pagePath, 'utf8');
const abilityModelsSource = readFileSync(abilityModelsPath, 'utf8');
const layoutSource = readFileSync(layoutPath, 'utf8');
const troubleshootingSource = readFileSync(troubleshootingPath, 'utf8');
const i18nSource = readFileSync(resolve(process.cwd(), 'src/lib/i18n.ts'), 'utf8');
const openCapabilityTemplateStart = pageSource.indexOf('function openCapabilityProviderTemplate');
const openCapabilityTemplateSource = openCapabilityTemplateStart >= 0
  ? pageSource.slice(openCapabilityTemplateStart, pageSource.indexOf('const resourceStatusLabel', openCapabilityTemplateStart))
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
  'Ability models must have a top-level admin navigation entry'
);

assert.ok(
  aiResourcesNavIndex < troubleshootingNavIndex,
  'AI resources must appear before Advanced Troubleshooting in primary navigation'
);

assert.ok(
  aiResourcesNavIndex < abilityModelsNavIndex && abilityModelsNavIndex < troubleshootingNavIndex,
  'Ability models must sit beside Provider Management before Advanced Troubleshooting'
);

assert.doesNotMatch(
  troubleshootingNavBlock,
  /\/admin\/ai-resources|\/admin\/ability-models/,
  'Advanced Troubleshooting must not own the provider management or ability model active paths'
);

assert.match(
  troubleshootingSource,
  /Related operations/,
  'Troubleshooting may expose AI resources only as a related operations link'
);

assert.match(
  troubleshootingSource,
  /Top-level model and capability supplier operations/,
  'Troubleshooting copy must explain provider management is a top-level operations entry'
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
  /'admin\.ai_resources\.title': '供应商管理'/,
  'Provider management page must provide Simplified Chinese translations'
);

assert.match(
  i18nSource,
  /'admin\.nav_ai_resources': '供应商管理'/,
  'Top-level admin navigation must call the surface Provider Management in Simplified Chinese'
);

assert.match(
  i18nSource,
  /'admin\.nav_ability_models': '能力模型'/,
  'Top-level admin navigation must expose Ability Models in Simplified Chinese'
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
  /useState<AIResourceView>\('connections'\)/,
  'AI resources page must default to the supplier list workflow'
);

assert.match(
  pageSource,
  /supplier_tab_model[\s\S]*supplier_tab_capability[\s\S]*tab_diagnostics/,
  'AI resources top-level tabs must stay focused on model suppliers, capability suppliers, and diagnostics'
);

assert.doesNotMatch(
  pageSource,
  /active=\{activeView === 'overview'\}/,
  'AI resources overview must not remain a top-level default tab'
);

assert.match(
  pageSource,
  /requestedView === 'overview'[\s\S]*setActiveView\('diagnostics'\)/,
  'Legacy overview deep links must land in diagnostics instead of restoring a separate overview page'
);

assert.match(
  abilityModelsSource,
  /fetch\('\/api\/admin\/ai-resources\/profile-preferences'/,
  'Ability models page must save only bounded profile preferences through the admin projection'
);

assert.match(
  abilityModelsSource,
  /type AbilityModelTab = 'wordpress' \| 'cloud'/,
  'Ability models page must keep only WordPress and Cloud-native top-level tabs explicitly'
);

assert.match(
  abilityModelsSource,
  /type CloudAbilityMediaTab = 'text' \| 'image' \| 'audio' \| 'video'/,
  'Cloud-native ability models must be grouped by text, image, audio, and video media tabs'
);

assert.match(
  abilityModelsSource,
  /useState<AbilityModelTab>\('wordpress'\)/,
  'Ability models page must default to the plugin ability defaults tab'
);

assert.match(
  abilityModelsSource,
  /tab_wordpress[\s\S]*tab_cloud/,
  'Ability models page must expose plugin ability and Cloud-native top-level tabs'
);

assert.doesNotMatch(
  abilityModelsSource,
  /activeAbilityTab === 'audio'|tab_audio/,
  'Audio ability models must not remain a top-level ability tab'
);

assert.match(
  abilityModelsSource,
  /\(\['text', 'image', 'audio', 'video'\] as CloudAbilityMediaTab\[\]\)\.map[\s\S]*cloud_media_tab_\$\{tab\}/,
  'Cloud-native ability models must expose text, image, audio, and video media tabs'
);

assert.match(
  abilityModelsSource,
  /activeAbilityTab === 'cloud'[\s\S]*activeCloudMediaTab === 'audio'[\s\S]*audioPreferenceRows\.map/,
  'Audio profile preferences must render only under the Cloud-native audio media tab'
);

assert.match(
  abilityModelsSource,
  /audioPreferenceRows[\s\S]*column_audio_ability[\s\S]*column_current_profile[\s\S]*column_configure_profile/,
  'Audio ability models must render as a scannable list with ability, current profile, and configuration columns'
);

assert.match(
  abilityModelsSource,
  /audioPreferenceRows\.map[\s\S]*row\.label[\s\S]*row\.description[\s\S]*row\.value[\s\S]*row\.update/,
  'Audio ability model rows must keep label, description, current value, and profile selector together'
);

assert.doesNotMatch(
  abilityModelsSource,
  /mt-4 grid gap-4 lg:grid-cols-3[\s\S]*audio_summary_text_profile_id/,
  'Audio ability models must not use the old three-column field layout'
);

assert.match(
  abilityModelsSource,
  /audioPreferenceRows/,
  'Audio profile preferences must live on the ability models page'
);

assert.match(
  abilityModelsSource,
  /audioPreferenceRows[\s\S]*audio_summary_text_profile_id/,
  'Audio profile preference rows must include the audio summary text profile binding'
);

assert.doesNotMatch(
  pageSource,
  /activeSupplierTab === 'model' && preferences/,
  'AI resource audio profile preferences must not stay under the model supplier tab'
);

assert.doesNotMatch(
  pageSource,
  /tab_ability_models/,
  'Provider Management must not expose Ability Models as an internal tab'
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
  /fetch\('\/api\/admin\/wordpress-ai-routing'/,
  'Ability models page must load and save Cloud runtime ability model routing through the bounded admin endpoint'
);

assert.match(
  pageSource,
  /BackofficeSummaryStrip/,
  'Provider management page must use a compact summary strip instead of oversized metric cards'
);

assert.match(
  abilityModelsSource,
  /BackofficeSummaryStrip/,
  'Ability models page must use a compact summary strip instead of oversized metric cards'
);

assert.match(
  abilityModelsSource,
  /activeAbilityTab === 'wordpress'[\s\S]*wordpress_title/,
  'Plugin ability model routing must render only under the plugin ability child tab'
);

assert.match(
  abilityModelsSource,
  /activeAbilityTab === 'cloud'[\s\S]*cloud_native_title/,
  'Ability models page must reserve a Cloud-native child tab without creating a second control plane'
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

assert.match(
  abilityModelsSource,
  /cloud_native_status_connected/,
  'Cloud-native existing abilities must expose a connected status instead of all planned placeholders'
);

assert.match(
  abilityModelsSource,
  /can_configure: boolean[\s\S]*disabled=\{!row\.can_configure\}[\s\S]*cloud_native_action_readonly/,
  'Cloud-native runtime projection rows must remain read-only unless the backend explicitly marks a row configurable'
);

assert.match(
  abilityModelsSource,
  /activeCloudNativeAbilityRows = cloudAbilityRows\.filter/,
  'Cloud-native ability media tabs must filter backend runtime projection rows'
);

assert.match(
  abilityModelsSource,
  /cloud_native_badge_readonly/,
  'Cloud-native ability section must not present the whole list as planned when existing runtime projections are connected'
);

assert.match(
  abilityModelsSource,
  /cloud_\$\{activeCloudMediaTab\}_empty_title[\s\S]*cloud_\$\{activeCloudMediaTab\}_empty_desc/,
  'Cloud-native video tab must stay as an explicit empty state until a video runtime contract exists'
);

assert.match(
  abilityModelsSource,
  /cloud_native_boundary_notice/,
  'Cloud-native planned ability rows must preserve the no-control-plane boundary notice'
);

assert.doesNotMatch(
  abilityModelsSource,
  /\/api\/admin\/cloud-ability-routing|saveCloudNativeAbility|generateIdempotencyKey\('cloud_ability/,
  'Cloud-native planned abilities must not introduce a fake Cloud ability routing write path'
);

assert.doesNotMatch(
  abilityModelsSource,
  /\/api\/admin\/plugin-ability-routing|savePluginAbilityOverride|generateIdempotencyKey\('plugin_ability/,
  'Plugin ability defaults must not introduce plugin-specific override persistence before the boundary is defined'
);

assert.match(
  abilityModelsSource,
  /abilityModelRows/,
  'Ability models page must render WordPress AI connector tasks as ability model rows'
);

assert.match(
  abilityModelsSource,
  /saveAbilityModelProfile/,
  'Ability models configuration must save the selected shared runtime profile'
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
  /verifiedModelIds[\s\S]*runtime_supported[\s\S]*setProviderModelIds\(verifiedModelIds\)/,
  'Provider channel catalog sync must only auto-enable runtime verified models'
);

assert.match(
  pageSource,
  /catalog_model_header_feature[\s\S]*catalog_model_status_catalog_only/,
  'Provider channel model preview must expose model feature and catalog-only status'
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
  /action_clear_all_models[\s\S]*action_fetch_upstream_models/,
  'Provider channel form must keep clear and catalog-sync actions in the catalog list header'
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
  /role="dialog"/,
  'AI resources provider form must open as an explicit dialog'
);

assert.match(
  pageSource,
  /Add provider/,
  'AI resources connections view must expose a compact add-provider action'
);

assert.match(
  pageSource,
  /Provider channels/,
  'AI resources connections view must list provider channels as the main working surface'
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

assert.match(
  pageSource,
  /SupplierSettingsTab/,
  'Provider management must split model suppliers and capability suppliers into operator tabs'
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
  /'admin\.ai_resources\.capability_supplier_list_title': '能力供应商列表'/,
  'Capability supplier list must provide Simplified Chinese copy'
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
  /isAiSupplier \? \(/,
  'AI resources provider edit/test/delete actions must be limited to AI suppliers'
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
  /<table className="min-w-\[1120px\]/,
  'AI resources provider channels must render as a compact table instead of large cards'
);

assert.match(
  pageSource,
  /Enabled \/ configured/,
  'AI resources provider channel table must expose enabled and configured state in one scannable column'
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

assert.match(
  pageSource,
  /Recent runtime evidence/,
  'AI resources page must expose recent runtime evidence for operator debugging'
);

assert.match(
  pageSource,
  /Capability Matrix/,
  'AI resources page must expose the capability-to-provider-model matrix'
);

assert.match(
  pageSource,
  /Runtime resolution/,
  'AI resources page must expose the current runtime resolution'
);

assert.match(
  pageSource,
  /Feature usage/,
  'AI resources page must expose feature-to-model usage'
);

assert.match(
  pageSource,
  /Model health/,
  'AI resources page must expose provider-model health diagnostics'
);

assert.match(
  pageSource,
  /Last 24h/,
  'Model health must expose a short diagnostic window'
);

assert.match(
  pageSource,
  /Last 7d/,
  'Model health must expose a longer diagnostic window'
);

assert.match(
  pageSource,
  /Feature-to-model evidence from Cloud runtime metadata/,
  'Feature usage must be framed as runtime metadata evidence'
);

assert.match(
  pageSource,
  /does not change routing, prompts, abilities, or WordPress writes/,
  'Feature usage must remain read-only and outside control-plane truth'
);

assert.match(
  pageSource,
  /Provider\/model health from provider_call_records/,
  'Model health must be backed by provider call metadata'
);

assert.match(
  pageSource,
  /Metadata only: prompts, results, and provider secrets are not exposed/,
  'Model health must not expose prompt, result, or secret material'
);

assert.match(
  pageSource,
  /Health alerts are diagnostic only and do not change routing, prompts, abilities, or WordPress writes/,
  'Model health must remain diagnostics-only'
);

assert.match(
  pageSource,
  /read-only diagnostics/,
  'Model health alerts must be framed as read-only diagnostics'
);

assert.match(
  pageSource,
  /read-only operator evidence, not a router editor/,
  'AI resources runtime resolution must not present itself as a router editor'
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

assert.match(
  pageSource,
  /Cloud runtime mapping from capability to profile, provider, model, and write posture/,
  'AI resources matrix must explain the runtime mapping purpose'
);

assert.match(
  pageSource,
  /not a WordPress ability editor/,
  'AI resources matrix must not present itself as a local ability editor'
);

assert.match(
  pageSource,
  /field_enabled/,
  'AI resources connections view must expose provider enabled state'
);

assert.match(
  pageSource,
  /field_configured/,
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

assert.match(
  pageSource,
  /Prompt and result content are not exposed here/,
  'AI resources runtime evidence must be metadata-only'
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
